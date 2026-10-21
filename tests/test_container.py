import copy
from contextlib import nullcontext
import io
import json
import unittest
from unittest import mock

from pybox import run_container
from pybox import container
from pybox.__main__ import main


class ContainerTests(unittest.TestCase):
    def setUp(self):
        observer = mock.Mock()
        observer.finish.return_value = container.observation.unknown("mocked collector")
        for patcher in [mock.patch.object(container, "_admission", side_effect=nullcontext),
                        mock.patch.object(container, "_Observer", return_value=observer),
                        mock.patch.object(container, "_reconcile_owned", return_value=container.CleanupResult(complete=True, admission_allowed=True)),
                        mock.patch.object(container, "_save_attempt"), mock.patch.object(container, "_clear_attempt")]:
            patcher.start()
            self.addCleanup(patcher.stop)
        owner = mock.patch.object(container, "_installation_owner", return_value="c" * 32)
        clock = mock.patch.object(container.time, "time", return_value=1700000000)
        owner.start()
        clock.start()
        self.addCleanup(owner.stop)
        self.addCleanup(clock.stop)

    def test_fixed_policy_and_immutable_local_image(self):
        args = container._create_args(dict(name="pybox-step3-" + "b" * 32,
                                      labels={"io.pybox.owner": "c" * 32, "io.pybox.run": "b" * 32,
                                              "io.pybox.expires": "1700000120"}))
        for flag in ["--pull=never", "--platform=linux/arm64", "--network=none", "--user=10000:10000",
                     "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only", "--memory=128m",
                     "--memory-swap=128m", "--pids-limit=32", "--cpus=0.5", "--log-driver=none", "--privileged=false"]:
            self.assertIn(flag, args)
        self.assertIn("/tmp:" + container.TMPFS, args)
        self.assertIn("nofile=128:128", args)
        self.assertEqual(args[-9:], [container.IMAGE, "-s", "KILL", "3", "python", "-I", "-B", "-u", "-"])
        self.assertIn("--entrypoint=timeout", args)
        self.assertNotIn("--rm", args)
        self.assertNotIn("--tty", args)
        self.assertNotIn("--env", args)
        self.assertNotIn("--volume", args)

    def test_request_validation_never_touches_docker(self):
        with mock.patch.object(container, "_guard") as guard:
            for source in [None, b"print(1)", "x" * 65537, "é" * 32769]:
                with self.subTest(source_type=type(source).__name__), self.assertRaises(ValueError):
                    run_container(source)
            # Up to 30 s is an opt-in (M9); anything above stays a request error.
            for timeout in [0, -1, 30.001, 31, True, float("nan"), float("inf"), 10 ** 400]:
                with self.subTest(timeout=str(timeout)[:20]), self.assertRaises(ValueError):
                    run_container("pass", timeout_s=timeout)
            for cap in [0, True, 65537, "64"]:
                with self.subTest(cap=cap), self.assertRaises(ValueError):
                    run_container("pass", max_output_bytes=cap)
            guard.assert_not_called()

    def test_three_mocked_round_trips_preserve_streams_state_and_removal(self):
        for source, stdout, stderr, exitcode in [
            ('print("hi")', "hi\n", "", 0),
            ('import sys; print("err", file=sys.stderr)', "", "err\n", 0),
            ("raise SystemExit(7)", "", "", 7),
        ]:
            with self.subTest(exitcode=exitcode, stderr=stderr):
                created = None
                running = False
                removed = False
                calls = []

                def capture(argv, input_data, timeout, cap, *, deadline=None):
                    nonlocal created, running, removed
                    args = argv[len(container.PREFIX):]
                    calls.append(args)
                    out, err, status = "", "", 0
                    if args[:2] == ["container", "create"]:
                        labels = dict(args[i + 1].split("=", 1) for i, flag in enumerate(args) if flag == "--label")
                        self.assertEqual(set(labels), {"io.pybox.checkpoint", "io.pybox.owner", "io.pybox.run", "io.pybox.expires"})
                        created = {"Id": "a" * 64, "Name": "/" + args[args.index("--name") + 1], "Config": {"Labels": labels}}
                        out = created["Id"] + "\n"
                    elif args[:2] == ["container", "start"]:
                        self.assertEqual(args[2:4], ["--attach", "--interactive"])
                        self.assertEqual(input_data, source.encode())
                        self.assertEqual(timeout, 2)
                        running = True
                        out, err, status = stdout, stderr, exitcode
                    elif args[:2] == ["container", "inspect"]:
                        data = copy.deepcopy(created)
                        data["State"] = {"Status": "exited" if running else "created", "Running": False,
                                         "ExitCode": exitcode if running else 0, "Error": "", "OOMKilled": False,
                                         "StartedAt": "2026-10-18T12:00:00Z" if running else "0001-01-01T00:00:00Z"}
                        out = json.dumps(data)
                    elif args[:2] == ["container", "rm"]:
                        removed = True
                    elif args[:2] == ["container", "ls"] and not removed:
                        out = created["Id"]
                    return dict(argv=argv, returncode=status, elapsed_s=0.01, timed_out=False, stdout=out, stderr=err,
                                stdout_truncated=False, stderr_truncated=False, output_complete=True, input_complete=True)

                with mock.patch.object(container, "_guard"), mock.patch.object(container, "_capture", side_effect=capture), mock.patch.object(container, "_check_policy"):
                    result = run_container(source)
                self.assertEqual((result.stdout, result.stderr, result.returncode), (stdout, stderr, exitcode))
                self.assertIsNone(result.runner_error)
                self.assertTrue(result.removed)
                self.assertEqual(result.inspection["State"]["Status"], "exited")
                self.assertEqual(calls[-2:], [["container", "rm", "--force", "a" * 64],
                                             ["container", "ls", "--all", "--quiet", "--no-trunc", "--filter", "id=" + "a" * 64]])
                self.assertTrue(any(args[:2] == ["container", "inspect"] for args in calls[2:-2]))

    def test_container_cli_reads_stdin_without_native_fallback(self):
        result = container.ContainerResult("container", "hi\n", "", 0, 0.01, False, False, False, True,
                                           None, "a" * 64, True, {}, [])
        stdin = io.TextIOWrapper(io.BytesIO(b'print("hi")\n'), encoding="utf-8")
        with mock.patch("sys.stdin", stdin), mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch("pybox.__main__.run_container", return_value=result) as run, mock.patch("pybox.__main__.run_file") as native:
            self.assertEqual(main(["container"]), 0)
            run.assert_called_once_with('print("hi")\n', timeout_s=2.0, max_output_bytes=65536)
            native.assert_not_called()

    def test_ambiguous_create_recovers_only_exact_name_and_owner_for_cleanup(self):
        token, cid = "b" * 32, "a" * 64
        name = "pybox-step3-" + token
        inspected = {"Id": cid, "Name": "/" + name,
                     "Config": {"Labels": {"io.pybox.owner": "c" * 32, "io.pybox.run": token, "io.pybox.expires": "1700000120"}},
                     "State": {"Status": "created", "Running": False, "ExitCode": 0, "Error": ""}}
        calls = []

        def capture(argv, input_data, timeout, cap, *, deadline=None):
            args = argv[len(container.PREFIX):]
            calls.append(args)
            out = ""
            failed = args[:2] == ["container", "create"]
            if args[:2] == ["container", "inspect"]:
                out = json.dumps(inspected)
            elif any(x.startswith("name=") for x in args):
                self.assertIn("name=^/" + name + "$", args)
                self.assertIn("label=io.pybox.owner=" + "c" * 32, args)
                self.assertIn("label=io.pybox.run=" + token, args)
                self.assertIn("label=io.pybox.expires=1700000120", args)
                out = cid + "\n"
            return dict(argv=argv, returncode=-9 if failed else 0, elapsed_s=0.01, timed_out=failed, stdout=out,
                        stderr="", stdout_truncated=False, stderr_truncated=False, output_complete=not failed, input_complete=True)

        with mock.patch.object(container, "_guard"), mock.patch.object(container.uuid, "uuid4") as nonce, mock.patch.object(container, "_capture", side_effect=capture):
            nonce.return_value.hex = token
            result = run_container("pass")
        self.assertTrue(result.removed)
        self.assertEqual(result.container_id, cid)
        self.assertIsNone(result.returncode)
        self.assertIsNotNone(result.runner_error)
        self.assertFalse(any(args[:2] == ["container", "start"] for args in calls))
        self.assertEqual(result.cleanup_status, "REMOVED")
        self.assertIn("create", result.timeouts)

    def test_engine_start_error_is_not_reported_as_target_exit(self):
        token, cid = "b" * 32, "a" * 64
        started = False
        removed = False

        def capture(argv, input_data, timeout, cap, *, deadline=None):
            nonlocal started, removed
            args = argv[len(container.PREFIX):]
            out = cid if args[:2] == ["container", "create"] else ""
            status = 0
            if args[:2] == ["container", "start"]:
                started, status = True, 125
            elif args[:2] == ["container", "inspect"]:
                out = json.dumps({"Id": cid, "Name": "/pybox-step3-" + token,
                                  "Config": {"Labels": {"io.pybox.owner": "c" * 32, "io.pybox.run": token,
                                                        "io.pybox.expires": "1700000120"}},
                                  "State": {"Status": "exited" if started else "created", "Running": False,
                                            "Error": "OCI start failed" if started else "", "ExitCode": 125 if started else 0,
                                            "StartedAt": "0001-01-01T00:00:00Z"}})
            elif args[:2] == ["container", "rm"]:
                removed = True
            elif args[:2] == ["container", "ls"] and not removed:
                out = cid
            return dict(argv=argv, returncode=status, elapsed_s=0.01, timed_out=False, stdout=out, stderr="",
                        stdout_truncated=False, stderr_truncated=False, output_complete=True, input_complete=True)

        with mock.patch.object(container, "_guard"), mock.patch.object(container, "_check_policy"), mock.patch.object(container.uuid, "uuid4") as nonce, mock.patch.object(container, "_capture", side_effect=capture):
            nonce.return_value.hex = token
            result = run_container("pass")
        self.assertIsNone(result.returncode)
        self.assertEqual(result.inspection["State"]["ExitCode"], 125)
        self.assertIsNotNone(result.runner_error)
        self.assertTrue(result.removed)


if __name__ == "__main__":
    unittest.main()
