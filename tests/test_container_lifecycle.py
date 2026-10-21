import copy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from pybox import container


def identity():
    return dict(name="pybox-step3-" + "b" * 32,
                labels={"io.pybox.owner": "c" * 32, "io.pybox.run": "b" * 32, "io.pybox.expires": "1700000120"})


class Engine:
    def __init__(self):
        self.cid = "a" * 64
        self.exists = False
        self.running = False
        self.started = False
        self.calls = []
        self.labels = identity()["labels"].copy()
        self.start_timeout = False
        self.create_error = False
        self.create_stderr = "engine unavailable"
        self.inject_after_create = False
        self.unavailable = False
        self.remove_error = False
        self.final_query_error = False
        self.extra_match = False
        self.mutate_label = None

    def __call__(self, argv, input_data, timeout, cap, *, deadline=None):
        args = argv[len(container.PREFIX):]
        self.calls.append(dict(args=args, timeout=timeout, deadline=deadline))
        out, status, timed_out = "", 0, False
        if self.unavailable:
            status = 1
        elif args[:2] == ["container", "create"]:
            if self.create_error:
                status = 1
            else:
                self.exists = True
                self.labels = dict(args[i + 1].split("=", 1) for i, flag in enumerate(args) if flag == "--label")
                if self.inject_after_create:
                    raise RuntimeError("injected after successful create acknowledgement")
                out = self.cid
        elif args[:2] == ["container", "start"]:
            self.started = True
            self.running = self.start_timeout
            timed_out = self.start_timeout
            status = -15 if timed_out else 0
        elif args[:2] == ["container", "ls"]:
            if self.final_query_error and not self.exists:
                status = 1
            elif self.exists:
                out = self.cid + ("\n" + "d" * 64 if self.extra_match else "")
        elif args[:2] == ["container", "inspect"]:
            labels = self.labels.copy()
            if self.mutate_label:
                labels[self.mutate_label] = "foreign"
            out = json.dumps(dict(Id=self.cid, Name="/" + identity()["name"], Config=dict(Labels=labels),
                                  State=dict(Status="running" if self.running else "exited" if self.started else "created",
                                             Running=self.running, ExitCode=137 if self.start_timeout and not self.running else 0,
                                             OOMKilled=False, Error="", StartedAt="2026-10-18T12:00:00Z" if self.started else "0001-01-01T00:00:00Z",
                                             FinishedAt="2026-10-18T12:00:01Z" if self.started and not self.running else "0001-01-01T00:00:00Z")))
        elif args[:2] == ["container", "kill"]:
            self.running = False
        elif args[:2] == ["container", "rm"]:
            if self.remove_error:
                status = 1
            else:
                self.exists = False
        else:
            raise AssertionError(args)
        err = self.create_stderr if args[:2] == ["container", "create"] else "engine unavailable"
        return dict(argv=argv, returncode=status, elapsed_s=0.01, timed_out=timed_out, stdout=out,
                    stderr=err if status == 1 else "", stdout_truncated=False,
                    stderr_truncated=False, output_complete=not timed_out, input_complete=not timed_out)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()
        observer = mock.Mock()
        observer.finish.return_value = container.observation.unknown("mocked collector")
        for patcher in [mock.patch.object(container, "_guard"),
                        mock.patch.object(container, "_Observer", return_value=observer),
                        mock.patch.object(container, "_admission", side_effect=nullcontext),
                        mock.patch.object(container, "_reconcile_owned", return_value=container.CleanupResult(complete=True, admission_allowed=True)),
                        mock.patch.object(container, "_save_attempt"), mock.patch.object(container, "_clear_attempt"),
                        mock.patch.object(container, "_installation_owner", return_value="c" * 32),
                        mock.patch.object(container, "_capture", side_effect=self.engine),
                        mock.patch.object(container, "_check_policy"),
                        mock.patch.object(container.uuid, "uuid4", return_value=mock.Mock(hex="b" * 32)),
                        mock.patch.object(container.time, "time", return_value=1700000000)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_labels_exist_before_create_and_all_bounds_are_recorded(self):
        result = container.run_container("pass")
        self.assertEqual(result.identity, identity())
        self.assertEqual(result.cleanup_status, "REMOVED")
        self.assertIsNone(result.runner_error)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.wall_deadline_monotonic, result.wall_start_monotonic + 2)
        for operation in result.operations:
            self.assertLessEqual(operation["timeout_budget_s"], container.OPERATION_TIMEOUTS[operation["phase"]])
        start = next(o for o in result.operations if o["phase"] == "start")
        self.assertEqual(start["deadline_monotonic"], result.wall_deadline_monotonic)

    def test_wall_timeout_uses_engine_kill_before_removal_and_not_client_exit(self):
        self.engine.start_timeout = True
        result = container.run_container("import time; time.sleep(8)", timeout_s=0.5)
        self.assertEqual(result.timeouts, ["wall"])
        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, 137)
        self.assertFalse(result.inspection["State"]["OOMKilled"])
        self.assertFalse(result.inspection["State"]["Running"])
        self.assertEqual(result.cleanup_status, "REMOVED")
        self.assertIsNone(result.runner_error)
        calls = [x["args"] for x in self.engine.calls]
        kill = ["container", "kill", "--signal=KILL", self.engine.cid]
        remove = ["container", "rm", "--force", self.engine.cid]
        self.assertLess(calls.index(kill), calls.index(remove))
        self.assertEqual(len([x for x in calls if x[:2] == ["container", "kill"]]), 1)
        self.assertFalse(result.output_complete)

    def test_missing_image_has_no_target_exit_and_observed_absence(self):
        self.engine.create_error = True
        result = container.run_container("pass")
        self.assertIsNone(result.returncode)
        self.assertIsNone(result.inspection)
        self.assertIsNone(result.wall_start_monotonic)
        self.assertEqual(result.cleanup_status, "UNCONFIRMED")
        self.assertFalse(result.removed)
        self.assertEqual(result.operations[-1]["stdout"], "")
        self.assertEqual(result.operations[-1]["returncode"], 0)
        self.assertFalse(self.engine.exists)
        self.assertIsNotNone(result.runner_error)
        self.assertFalse(any(x["args"][:2] == ["container", "start"] for x in self.engine.calls))

    def test_post_create_failure_recovers_full_identity_without_start(self):
        self.engine.inject_after_create = True
        result = container.run_container("pass")
        self.assertEqual(result.container_id, self.engine.cid)
        self.assertEqual(result.cleanup_status, "REMOVED")
        self.assertEqual(result.inspection["State"]["Status"], "created")
        self.assertIsNone(result.returncode)
        query = self.engine.calls[1]["args"]
        for key, value in result.identity["labels"].items():
            self.assertIn("label=" + key + "=" + value, query)
        self.assertFalse(any(x["args"][:2] == ["container", "start"] for x in self.engine.calls))

    def test_completed_missing_image_rejection_and_empty_query_confirms_not_created(self):
        self.engine.create_error = True
        self.engine.create_stderr = "Error response from daemon: No such image: " + container.IMAGE + "\n"
        result = container.run_container("pass")
        self.assertEqual(result.cleanup_status, "NOT_CREATED")
        self.assertFalse(result.removed)
        self.assertIsNone(result.container_id)
        self.assertIsNone(result.returncode)
        self.assertIsNone(result.inspection)
        self.assertIsNone(result.wall_start_monotonic)
        self.assertFalse(result.output_complete)
        self.assertEqual(result.timeouts, [])
        self.assertIn("Docker create failed", result.runner_error)
        self.assertNotIn("UNCONFIRMED", result.runner_error)
        self.assertEqual([o["phase"] for o in result.operations], ["create", "query"])
        query = self.engine.calls[-1]["args"]
        self.assertIn("name=^/" + result.identity["name"] + "$", query)
        for key, value in result.identity["labels"].items():
            self.assertIn("label=" + key + "=" + value, query)
        self.assertTrue(result.operations[-1]["output_complete"])
        self.assertFalse(result.operations[-1]["stdout_truncated"])
        self.assertFalse(result.operations[-1]["stderr_truncated"])
        self.assertEqual(result.operations[-1]["returncode"], 0)
        self.assertEqual(result.operations[-1]["stdout"], "")

    def test_completed_rejection_with_failed_or_incomplete_query_stays_unconfirmed(self):
        self.engine.create_error = True
        self.engine.create_stderr = "Error response from daemon: No such image: " + container.IMAGE
        for mutation in [dict(returncode=1), dict(timed_out=True), dict(output_complete=False),
                         dict(stdout_truncated=True), dict(stderr_truncated=True), dict(stdout="a\nb")]:
            with self.subTest(mutation=mutation):
                self.engine.calls.clear()

                def capture(*args, **kwargs):
                    result = self.engine(*args, **kwargs)
                    if args[0][len(container.PREFIX) + 1] == "ls":
                        result.update(mutation)
                    return result

                with mock.patch.object(container, "_capture", side_effect=capture):
                    result = container.run_container("pass")
                self.assertEqual(result.cleanup_status, "UNCONFIRMED")
                self.assertFalse(result.removed)
                self.assertIsNone(result.returncode)
                self.assertIsNone(result.container_id)
                self.assertIn("UNCONFIRMED", result.runner_error)
                self.assertEqual([o["phase"] for o in result.operations], ["create", "query"])

    def test_other_completed_daemon_rejections_and_empty_query_confirm_not_created(self):
        self.engine.create_error = True
        for diagnostic, status in [
            ('Error response from daemon: Conflict. The container name "/existing" is already in use.\n'
             'You have to remove (or rename) that container to be able to reuse that name.\n', 1),
            ('Error response from daemon: invalid configuration', 125),
        ]:
            with self.subTest(diagnostic=diagnostic, status=status):
                self.engine.calls.clear()
                self.engine.create_stderr = diagnostic

                def capture(*args, **kwargs):
                    result = self.engine(*args, **kwargs)
                    if args[0][len(container.PREFIX) + 1] == "create":
                        result["returncode"] = status
                    return result

                with mock.patch.object(container, "_capture", side_effect=capture):
                    result = container.run_container("pass")
                self.assertEqual(result.cleanup_status, "NOT_CREATED")
                self.assertFalse(result.removed)
                self.assertIsNone(result.container_id)
                self.assertIsNone(result.returncode)
                self.assertIsNone(result.inspection)
                self.assertIn("Docker create failed", result.runner_error)
                self.assertNotIn("UNCONFIRMED", result.runner_error)
                self.assertEqual([o["phase"] for o in result.operations], ["create", "query"])
                self.assertEqual(result.operations[-1]["stdout"], "")
                self.assertEqual(result.operations[-1]["returncode"], 0)
                for key, value in result.identity["labels"].items():
                    self.assertIn("label=" + key + "=" + value, self.engine.calls[-1]["args"])

    def test_cancelled_transport_or_incomplete_create_never_confirms_noncreation(self):
        self.engine.create_error = True
        self.engine.create_stderr = "Error response from daemon: No such image: " + container.IMAGE
        for mutation in [dict(returncode=-9), dict(returncode=0),
                         dict(returncode=125, stderr="docker: unknown flag --unrecognized"), dict(timed_out=True),
                         dict(output_complete=False), dict(stdout_truncated=True), dict(stderr_truncated=True),
                         dict(stdout="unexpected acknowledgement"), dict(stderr="engine unavailable"),
                         dict(stderr="error during connect: EOF"),
                         dict(stderr="Error response from daemon:"),
                         dict(stderr="Error response from daemon: \n \t"),
                         dict(stderr="Error response from daemon: context deadline exceeded"),
                         dict(stderr="Error response from daemon: rpc error: code = DeadlineExceeded desc = create request expired"),
                         dict(stderr="Error response from daemon: context canceled"),
                         dict(stderr="Error response from daemon: context cancelled"),
                         dict(stderr="Error response from daemon: i/o timeout"),
                         dict(stderr="Error response from daemon: operation timed out"),
                         dict(stderr="Error response from daemon: EOF"),
                         dict(stderr="prefix: " + self.engine.create_stderr),
                         dict(stderr="error during connect: EOF\n" + self.engine.create_stderr)]:
            with self.subTest(mutation=mutation):
                self.engine.calls.clear()

                def capture(*args, **kwargs):
                    result = self.engine(*args, **kwargs)
                    if args[0][len(container.PREFIX) + 1] == "create":
                        result.update(mutation)
                    return result

                with mock.patch.object(container, "_capture", side_effect=capture):
                    result = container.run_container("pass")
                self.assertEqual(result.cleanup_status, "UNCONFIRMED")
                self.assertFalse(result.removed)
                self.assertIsNone(result.returncode)
                self.assertIsNone(result.container_id)
                self.assertEqual(result.operations[-1]["stdout"], "")
                self.assertEqual(result.operations[-1]["returncode"], 0)
                self.assertIn("late object", result.runner_error)
                self.assertEqual([o["phase"] for o in result.operations], ["create", "query"])

    def test_completed_rejection_does_not_bypass_found_object_identity_guard(self):
        self.engine.create_error = True
        self.engine.create_stderr = "Error response from daemon: No such image: " + container.IMAGE
        self.engine.exists = True
        self.engine.mutate_label = "io.pybox.owner"
        result = container.run_container("pass")
        self.assertEqual(result.cleanup_status, "UNCONFIRMED")
        self.assertFalse(result.removed)
        self.assertTrue(self.engine.exists)
        self.assertIsNone(result.returncode)
        self.assertFalse(any(x["args"][1] in {"start", "kill", "rm"} for x in self.engine.calls))

    def test_unreachable_engine_never_reports_absence_or_cleanup_success(self):
        self.engine.unavailable = True
        result = container.run_container("pass")
        self.assertEqual(result.cleanup_status, "UNCONFIRMED")
        self.assertFalse(result.removed)
        self.assertIsNone(result.returncode)
        self.assertIsNone(result.inspection)
        self.assertIn("UNCONFIRMED", result.runner_error)
        self.assertEqual([o["phase"] for o in result.operations], ["create", "query"])

    def test_every_ownership_label_mismatch_prevents_destructive_commands(self):
        for label in identity()["labels"]:
            with self.subTest(label=label):
                self.engine.calls.clear()
                self.engine.exists = True
                self.engine.mutate_label = label
                control = container._Control(identity(), self.engine.cid)
                control.cleanup()
                self.assertEqual(control.cleanup_status, "UNCONFIRMED")
                self.assertTrue(self.engine.exists)
                self.assertFalse(any(x["args"][1] in {"kill", "rm"} for x in self.engine.calls))

    def test_ambiguous_identity_query_never_removes_any_object(self):
        self.engine.exists = True
        self.engine.extra_match = True
        control = container._Control(identity())
        control.cleanup()
        self.assertEqual(control.cleanup_status, "UNCONFIRMED")
        self.assertEqual(len(self.engine.calls), 1)

    def test_late_create_after_empty_query_does_not_claim_cleanup_success(self):
        def capture(*args, **kwargs):
            result = self.engine(*args, **kwargs)
            operation = args[0][len(container.PREFIX) + 1]
            if operation == "create":
                self.engine.exists = False
                result.update(returncode=-15, timed_out=True, output_complete=False)
            elif operation == "ls":
                self.engine.exists = True
            return result

        with mock.patch.object(container, "_capture", side_effect=capture):
            result = container.run_container("pass")
        self.assertTrue(self.engine.exists)
        self.assertIsNone(result.container_id)
        self.assertEqual(result.cleanup_status, "UNCONFIRMED")
        self.assertFalse(result.removed)
        self.assertIn("late object", result.runner_error)
        self.assertFalse(any(x["args"][1] in {"kill", "rm"} for x in self.engine.calls))

    def test_mismatched_full_id_or_name_prevents_destructive_commands(self):
        for field, value in [("Id", "d" * 64), ("Name", "/foreign")]:
            with self.subTest(field=field):
                self.engine.calls.clear()
                self.engine.exists = True

                def capture(*args, **kwargs):
                    result = self.engine(*args, **kwargs)
                    if args[0][len(container.PREFIX) + 1] == "inspect":
                        data = json.loads(result["stdout"])
                        data[field] = value
                        result["stdout"] = json.dumps(data)
                    return result

                with mock.patch.object(container, "_capture", side_effect=capture):
                    control = container._Control(identity(), self.engine.cid)
                    control.cleanup()
                self.assertEqual(control.cleanup_status, "UNCONFIRMED")
                self.assertFalse(any(x["args"][1] in {"kill", "rm"} for x in self.engine.calls))

    def test_remove_error_and_unobserved_absence_remain_unconfirmed(self):
        for failure in ["remove_error", "final_query_error"]:
            with self.subTest(failure=failure):
                self.engine.remove_error = failure == "remove_error"
                self.engine.final_query_error = failure == "final_query_error"
                result = container.run_container("pass")
                self.assertEqual(result.cleanup_status, "UNCONFIRMED")
                self.assertFalse(result.removed)
                self.assertIsNotNone(result.runner_error)

    def test_cleanup_budget_origin_is_not_reset_after_a_blocking_query(self):
        self.engine.exists = True
        clock = [100.0]

        def capture(*args, **kwargs):
            result = self.engine(*args, **kwargs)
            clock[0] += container.CLEANUP_BUDGET_S + 1
            return result

        with mock.patch.object(container.time, "monotonic", side_effect=lambda: clock[0]), mock.patch.object(container, "_capture", side_effect=capture):
            control = container._Control(identity(), self.engine.cid)
            control.cleanup()
        self.assertEqual(control.cleanup_status, "UNCONFIRMED")
        self.assertIn("cleanup_budget", control.timeouts)
        self.assertEqual(len(self.engine.calls), 1)
        self.assertFalse(control.operations[-1]["executed"])

    def test_wall_deadline_is_not_reset_after_a_blocking_start(self):
        clock = [100.0]

        def capture(*args, **kwargs):
            result = self.engine(*args, **kwargs)
            if args[0][len(container.PREFIX) + 1] == "start":
                clock[0] += 3
            return result

        with mock.patch.object(container.time, "monotonic", side_effect=lambda: clock[0]), mock.patch.object(container, "_capture", side_effect=capture):
            result = container.run_container("pass")
        self.assertEqual(result.wall_start_monotonic, 100)
        self.assertEqual(result.wall_deadline_monotonic, 102)
        self.assertIn("wall", result.timeouts)
        self.assertEqual(result.cleanup_status, "REMOVED")

    def test_restored_reconciliation_does_not_rewrite_original_unknown(self):
        self.engine.unavailable = True
        original = container.run_container("pass")
        saved = copy.deepcopy(original)
        self.engine.unavailable = False
        recovery = container._Control(original.identity, original.container_id)
        recovery.cleanup()
        self.assertEqual(recovery.cleanup_status, "UNCONFIRMED")
        self.assertEqual(recovery.operations[-1]["stdout"], "")
        self.assertEqual(recovery.operations[-1]["returncode"], 0)
        self.assertEqual(original, saved)
        self.assertEqual(original.cleanup_status, "UNCONFIRMED")


class InstallationMetadataTests(unittest.TestCase):
    def test_private_owner_is_stable_and_not_replaced(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(container, "_guard"), mock.patch.object(container, "OWNER_FILE", Path(root).resolve() / "installation.json"):
            first = container._installation_owner()
            path = container.OWNER_FILE
            before = path.read_bytes()
            self.assertEqual(container._installation_owner(), first)
            self.assertEqual(path.read_bytes(), before)
            self.assertRegex(first, r"^[0-9a-f]{32}$")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_bad_metadata_is_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(container, "_guard"), mock.patch.object(container, "OWNER_FILE", Path(root).resolve() / "installation.json"):
            path = container.OWNER_FILE
            for data in [b"{}", b'bad json', b'{"version":true,"owner":"cccccccccccccccccccccccccccccccc"}']:
                path.write_bytes(data)
                path.chmod(0o600)
                with self.assertRaises((ValueError, RuntimeError)):
                    container._installation_owner()
                self.assertEqual(path.read_bytes(), data)

    def test_nonprivate_or_linked_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(container, "_guard"), mock.patch.object(container, "OWNER_FILE", Path(root).resolve() / "installation.json"):
            path = container.OWNER_FILE
            container._installation_owner()
            path.chmod(0o644)
            with self.assertRaises(RuntimeError):
                container._installation_owner()
            path.chmod(0o600)
            alias = path.with_name("alias.json")
            os.link(path, alias)
            with self.assertRaises(RuntimeError):
                container._installation_owner()
            alias.unlink()
            path.unlink()
            path.symlink_to(alias)
            with self.assertRaises(OSError):
                container._installation_owner()


class CaptureDeadlineTests(unittest.TestCase):
    def test_absolute_deadline_survives_blocking_popen(self):
        popen = subprocess.Popen
        monotonic = time.monotonic
        offset = [0.0]

        def spawn(*args, **kwargs):
            process = popen(*args, **kwargs)
            offset[0] = 10.0
            return process

        with mock.patch.object(container.subprocess, "Popen", side_effect=spawn), mock.patch.object(container.time, "monotonic", side_effect=lambda: monotonic() + offset[0]), mock.patch.object(container.os, "killpg", wraps=os.killpg) as kill:
            deadline = time.monotonic() + 0.1
            result = container._capture([sys.executable, "-I", "-B", "-u", "-c", "import time; time.sleep(0.2)"],
                                        timeout_s=2, deadline=deadline)
        self.assertTrue(result["timed_out"])
        self.assertIsNotNone(result["returncode"])
        self.assertTrue(kill.called)
        self.assertTrue(all(call.args[1] == signal.SIGKILL for call in kill.call_args_list))
        self.assertEqual(result["returncode"], -signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
