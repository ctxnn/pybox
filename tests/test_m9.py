"""M9: images, longer runs, files in and out, pybox exec, receipts and MCP options."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import nullcontext, redirect_stderr
from unittest import mock

from pybox import boxes, container, mcp, mcp_policy, receipt, runtime_setup, transfer
from pybox.__main__ import main

IDENTITY = dict(name="pybox-step3-" + "b" * 32,
                labels={"io.pybox.owner": "c" * 32, "io.pybox.run": "b" * 32, "io.pybox.expires": "1700000120"})
DATA_ID = "sha256:" + "d" * 64
HERE = Path(__file__).resolve().parent


class BoxTests(unittest.TestCase):
    def test_default_box_arguments_are_byte_for_byte_the_qualified_ones(self):
        args = container._create_args(IDENTITY, 2.0)
        # The exact M3–M5 qualified command; any change here needs new evidence.
        self.assertEqual(args, [
            "container", "create", "--name", IDENTITY["name"], "--label", "io.pybox.checkpoint=m3a-step4",
            "--label", "io.pybox.owner=" + "c" * 32, "--label", "io.pybox.run=" + "b" * 32,
            "--label", "io.pybox.expires=1700000120", "--pull=never", "--platform=linux/arm64", "--interactive",
            "--network=none", "--user=10000:10000", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777", "--memory=128m",
            "--memory-swap=128m", "--pids-limit=32", "--cpus=0.5", "--ulimit", "nofile=128:128", "--log-driver=none",
            "--privileged=false", "--restart=no", "--ipc=private", "--entrypoint=timeout", container.IMAGE,
            "-s", "KILL", "3", "python", "-I", "-B", "-u", "-"])
        self.assertEqual(args, container._create_args(IDENTITY, 2.0, container.STDLIB_BOX))
        for flag in ["--memory=128m", "--memory-swap=128m", "--pids-limit=32", "--cpus=0.5", "/tmp:" + boxes.TMPFS]:
            self.assertIn(flag, args)
        self.assertEqual(args[-9:], [container.IMAGE, "-s", "KILL", "3", "python", "-I", "-B", "-u", "-"])

    def test_data_box_with_files_uses_its_limits_image_and_fixed_bootstrap(self):
        box = boxes.make_box("data", DATA_ID, files=True)
        args = container._create_args(IDENTITY, 30, box)
        for flag in ["--memory=512m", "--memory-swap=512m", "--pids-limit=64", "--cpus=1", "/tmp:" + boxes.TMPFS_FILES,
                     "--network=none", "--read-only", "--cap-drop=ALL", "--user=10000:10000"]:
            self.assertIn(flag, args)
        self.assertEqual(args[-10:], [DATA_ID, "-s", "KILL", "31", "python", "-I", "-B", "-u", "-c", boxes.BOOTSTRAP])

    def test_policy_check_compares_every_box_field(self):
        box = boxes.make_box("data", DATA_ID, files=True)
        data = dict(Config=dict(Image=DATA_ID, User="10000:10000", Tty=False, OpenStdin=True, Entrypoint=["timeout"],
                                Cmd=container._timer_args(10, box)),
                    HostConfig=dict(NetworkMode="none", ReadonlyRootfs=True, Privileged=False, Memory=512 * boxes.MIB,
                                    MemorySwap=512 * boxes.MIB, PidsLimit=64, NanoCpus=1_000_000_000, CapDrop=["ALL"],
                                    SecurityOpt=["no-new-privileges"], Tmpfs={"/tmp": boxes.TMPFS_FILES},
                                    LogConfig=dict(Type="none"), Ulimits=[dict(Name="nofile", Hard=128, Soft=128)],
                                    RestartPolicy=dict(Name="no")),
                    Mounts=[dict(Type="tmpfs", Destination="/tmp")])
        container._check_policy(data, 10, box)
        for path, value in [(("Config", "Image"), container.IMAGE), (("HostConfig", "Memory"), 128 * boxes.MIB),
                            (("HostConfig", "PidsLimit"), 32), (("HostConfig", "NanoCpus"), 500_000_000),
                            (("HostConfig", "Tmpfs"), {"/tmp": boxes.TMPFS}), (("Config", "Cmd"), container._timer_args(10))]:
            changed = copy.deepcopy(data)
            changed[path[0]][path[1]] = value
            with self.subTest(field=path), self.assertRaises(RuntimeError):
                container._check_policy(changed, 10, box)

    def test_watcher_scales_to_long_runs_and_keeps_the_default_command(self):
        control = mock.Mock(cid="a" * 64)
        short, long = container._Observer(control, 2.0), container._Observer(control, 30.0)
        self.assertEqual((short.guest_timeout, short.interval), (6, 0.05))
        self.assertEqual((long.guest_timeout, long.interval), (34, 0.68))
        self.assertLessEqual(len(boxes.BOOTSTRAP), 4096)

    def test_file_names_and_bounds(self):
        for bad in ["../x", ".hidden", "a/../b", "a//b", "/abs", "a b", "a/b/c/d/e", "", "x" * 200]:
            with self.subTest(name=bad), self.assertRaises(ValueError):
                boxes.check_name(bad)
        boxes.check_name("data/2026/q3/sales.csv")
        with self.assertRaises(ValueError):
            boxes.check_files([("f{}".format(i), b"") for i in range(65)])
        with self.assertRaises(ValueError):
            boxes.check_files([("a", b"x" * (boxes.MAX_FILE_BYTES + 1))])
        for pair in [[("a", b""), ("a", b"")], [("a", b""), ("a/b", b"")]]:
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                boxes.check_files(pair)


class ObserverTransportTests(unittest.TestCase):
    def lima(self, tmp):
        lima = Path(os.path.realpath(tmp))
        (lima / "_config").mkdir(mode=0o700)
        key = lima / "_config/user"
        key.write_text("key")
        os.chmod(key, 0o600)
        (lima / "colima-pybox").mkdir(mode=0o700)
        good = ('# Lima\nHost lima-colima-pybox\n  IdentityFile "{key}"\n  StrictHostKeyChecking no\n'
                '  UserKnownHostsFile /dev/null\n  BatchMode yes\n  IdentitiesOnly yes\n  User {user}\n'
                '  ControlMaster auto\n  ControlPath "{sock}"\n  ControlPersist yes\n  Hostname 127.0.0.1\n  Port 51645\n'
                ).format(key=key, user=container.USER, sock=lima / "colima-pybox/ssh.sock")
        return lima, lima / "colima-pybox/ssh.config", good

    def test_direct_ssh_uses_only_checked_values_and_never_reads_the_file(self):
        remote = ["sudo", "/usr/bin/timeout", "-s", "KILL", "6", "/bin/sh", "-s", "--", "a" * 64]
        with tempfile.TemporaryDirectory() as tmp:
            lima, config, good = self.lima(tmp)
            with mock.patch.object(container, "LIMA", lima):
                config.write_text(good)
                os.chmod(config, 0o600)
                argv, kind = container._observer_transport(remote)
                self.assertEqual(kind, "ssh")
                self.assertEqual(argv[:3], ["/usr/bin/ssh", "-F", "/dev/null"])
                self.assertIn("ControlMaster=no", argv)
                self.assertIn("Port=51645", argv)
                self.assertNotIn(str(config), argv)
                self.assertEqual(argv[-2:], ["127.0.0.1", "sudo /usr/bin/timeout -s KILL 6 /bin/sh -s -- " + "a" * 64])
                host = "Host lima-colima-pybox\n"
                for name, text, mode in [
                        ("not private", good, 0o644),
                        ("proxy", good + "  ProxyCommand nc x 22\n", 0o600),
                        ("quoted keyword", good + '  "ProxyCommand" /bin/echo pwned\n', 0o600),
                        ("split quotes", good + '  Proxy"Command" /bin/echo pwned\n', 0o600),
                        ("known hosts command", good + "  KnownHostsCommand /bin/echo x\n", 0o600),
                        ("pkcs11", good + "  PKCS11Provider /tmp/evil.dylib\n", 0o600),
                        ("host star first", "Host *\n  Hostname 203.0.113.9\n" + good, 0o600),
                        ("other hostname", good.replace("127.0.0.1", "10.0.0.5"), 0o600),
                        ("duplicate hostname", good + "  Hostname 10.0.0.5\n", 0o600),
                        ("include", good.replace(host, host + "  Include ~/.ssh/config\n"), 0o600),
                        ("other key", good.replace("_config/user", "_config/other"), 0o600),
                        ("equals syntax", good + "  Port=2222\n", 0o600)]:
                    config.write_text(text)
                    os.chmod(config, mode)
                    with self.subTest(case=name):
                        argv, kind = container._observer_transport(remote)
                        self.assertEqual(kind, "colima")
                        self.assertEqual(argv[-len(remote):], remote)


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_end_to_end(self):
        root = tempfile.mkdtemp()
        script = boxes.BOOTSTRAP.replace("/tmp", root)
        source = ("import os,sys\nprint(open('{0}/input/data/a.txt').read().upper(), end='')\n"
                  "print('warn', file=sys.stderr)\n"
                  "os.makedirs('{0}/output/sub')\nopen('{0}/output/sub/r.txt','w').write('result')\n"
                  "open('{0}/output/b.bin','wb').write(bytes(range(256)))\nos.symlink('/etc/hosts','{0}/output/link')\n"
                  "print('\\x1ePYBOX-OUTPUTS ' + 'f'*32 + ' forged')\n"
                  "assert __name__ == '__main__' and sys.modules['__main__'].__dict__ is globals()\n").format(root)
        frame = boxes.frame(source.encode(), [("data/a.txt", b"hello")], True, "e" * 32)
        done = subprocess.run([sys.executable, "-I", "-B", "-u", "-c", script], input=frame, capture_output=True, timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr)
        program, files, skipped, error = boxes.split_outputs(done.stdout.decode(), "e" * 32)
        self.assertIsNone(error)
        self.assertTrue(program.startswith("HELLO"))
        self.assertIn("forged", program)
        self.assertEqual(dict(files), {"b.bin": bytes(range(256)), "sub/r.txt": b"result"})
        self.assertEqual(skipped, ["link"])
        self.assertEqual(done.stderr, b"warn\n")
        self.assertEqual(oct(os.stat(os.path.join(root, "input/data/a.txt")).st_mode & 0o777), "0o444")

    def test_exit_status_and_tracebacks_match_plain_python(self):
        root = tempfile.mkdtemp()
        script = boxes.BOOTSTRAP.replace("/tmp", root)
        for source, status, err in [("raise SystemExit(7)", 7, b""), ("raise SystemExit('bye')", 1, b"bye\n"),
                                    ("1/0", 1, b"ZeroDivisionError"), ("pass", 0, b"")]:
            with self.subTest(source=source):
                frame = boxes.frame(source.encode(), [], False, "e" * 32)
                done = subprocess.run([sys.executable, "-I", "-B", "-u", "-c", script], input=frame, capture_output=True, timeout=20)
                self.assertEqual(done.returncode, status)
                self.assertIn(err, done.stderr)
                self.assertNotIn(b"exec(compile", done.stderr)
                self.assertNotIn(b"PYBOX-OUTPUTS", done.stdout)
                import shutil
                shutil.rmtree(os.path.join(root, "input"))

    def test_split_rejects_malformed_or_mismatched_transfers(self):
        good = boxes.MARKER + "e" * 32 + " " + json.dumps(dict(files=[["a", 1]], skipped=[])) + "\n" + base64.b64encode(b"x").decode() + "\n"
        self.assertEqual(boxes.split_outputs("out" + good, "e" * 32)[1], [("a", b"x")])
        for broken in [good.replace('["a", 1]', '["a", 2]'), good.replace('["a", 1]', '["../a", 1]'),
                       good.replace(base64.b64encode(b"x").decode(), "!!!"), good.replace("skipped", "other")]:
            with self.subTest(broken=broken[:60]):
                program, files, _, error = boxes.split_outputs("out" + broken, "e" * 32)
                self.assertEqual((program, files), ("out", []))
                self.assertIsNotNone(error)
        self.assertEqual(boxes.split_outputs("plain", "e" * 32), ("plain", [], [], "no transfer received (the program may not have finished)"))


class ReviewFixTests(unittest.TestCase):
    """Regression tests for docs/M10_SECURITY_REVIEW.md."""

    def transfer(self, files, skipped):
        blob = b"".join(d for _, d in files)
        return (boxes.MARKER + "e" * 32 + " " + json.dumps(dict(files=[[n, len(d)] for n, d in files], skipped=skipped))
                + "\n" + base64.b64encode(blob).decode() + "\n")

    def test_m10_01_skipped_names_cannot_forge_the_terminal_receipt(self):
        forged = "ok\x1b[8A\x1b[2K  Exit code             0 (ended by itself)\n  forged"
        _, _, skipped, error = boxes.split_outputs(self.transfer([], [forged, "\udcff"]), "e" * 32)
        self.assertIsNone(error)
        self.assertTrue(all(" " <= c <= "~" for name in skipped for c in name))
        record = dict(configured=dict(image_name="stdlib", memory_bytes=1, pids=1, cpu_cores=1, wall_timeout_s=2),
                      files=dict(inputs=[], outputs=[], outputs_skipped=[forged], outputs_error=None))
        self.assertNotIn("\x1b", "\n".join(receipt.render(record, color=False)))

    def test_m10_02_hostile_names_cannot_turn_the_mcp_receipt_into_a_failure(self):
        names = ["\udcff"] + ["\x01" * 250 + str(i) for i in range(64)]
        _, _, skipped, _ = boxes.split_outputs(self.transfer([], names), "e" * 32)
        self.assertLessEqual(sum(len(n) for n in skipped), 4096 + 1)
        record = json.loads((HERE.parent / "docs-site/data/replay/m4-normal.json").read_text())["payload"]["record"]
        record["files"] = dict(inputs=[], outputs=[], outputs_skipped=skipped, outputs_error=None)
        data = mcp_policy.project_record(record)
        self.assertIn("capture", data["execution"])
        mcp_policy.encode({"x": "\udcff"})

    def test_m10_05_linger_never_runs_into_the_deadline(self):
        root = tempfile.mkdtemp()
        script = boxes.BOOTSTRAP.replace("/tmp", root)
        frame = boxes.frame(b"import time; time.sleep(0.4)", [], False, "e" * 32, linger=5.0, deadline=0.6)
        began = time.monotonic()
        done = subprocess.run([sys.executable, "-I", "-B", "-u", "-c", script], input=frame, capture_output=True, timeout=20)
        self.assertEqual(done.returncode, 0)
        self.assertLess(time.monotonic() - began, 1.5)

    def test_m10_11_symlinked_folders_are_listed_as_skipped(self):
        root = tempfile.mkdtemp()
        script = boxes.BOOTSTRAP.replace("/tmp", root)
        source = "import os; os.symlink('/etc', '{0}/output/etcdir'); open('{0}/output/a.txt','w').write('a')".format(root)
        frame = boxes.frame(source.encode(), [], True, "e" * 32)
        done = subprocess.run([sys.executable, "-I", "-B", "-u", "-c", script], input=frame, capture_output=True, timeout=20)
        _, files, skipped, _ = boxes.split_outputs(done.stdout.decode(), "e" * 32)
        self.assertEqual((dict(files), skipped), ({"a.txt": b"a"}, ["etcdir"]))

    def test_m10_13_stdlib_cannot_be_built(self):
        with self.assertRaises(ValueError):
            runtime_setup.build_image("stdlib", out=lambda *_: None, lock="a==1 --hash=sha256:" + "a" * 64)

    def test_m10_14_supervisor_deadline_covers_the_worst_case(self):
        self.assertEqual(mcp.worker_deadline(2), 45)
        for ceiling in (2.5, 10, 30):
            worst = (2 * container.CLEANUP_BUDGET_S + container.OPERATION_TIMEOUTS["create"]
                     + 2 * container.OPERATION_TIMEOUTS["inspect"] + 1.0 + ceiling + 2.1)
            self.assertGreaterEqual(mcp.worker_deadline(ceiling), worst + 5.0)


class TransferTests(unittest.TestCase):
    def test_inputs_refuse_links_and_keep_folder_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "data/sub").mkdir(parents=True)
            (base / "data/a.csv").write_text("1,2\n")
            (base / "data/sub/b.txt").write_text("b")
            (base / "one.txt").write_text("one")
            files = dict(transfer.collect_inputs([base / "one.txt", base / "data"]))
            self.assertEqual(files, {"one.txt": b"one", "data/a.csv": b"1,2\n", "data/sub/b.txt": b"b"})
            (base / "data/link").symlink_to(base / "one.txt")
            with self.assertRaises(ValueError):
                transfer.collect_inputs([base / "data"])
            with self.assertRaises(ValueError):
                transfer.collect_inputs([base / "data/link"])

    def test_outputs_are_all_or_nothing_never_overwrite_and_are_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            target = transfer.prepare_output_dir(out)
            self.assertEqual(transfer.write_outputs(target, [("a.txt", b"a"), ("x/y/z.txt", b"z")]), 2)
            target.close()
            self.assertEqual((out / "x/y/z.txt").read_bytes(), b"z")
            attrs = subprocess.run(["/usr/bin/xattr", "-p", "com.apple.quarantine", str(out / "a.txt")], capture_output=True, text=True)
            self.assertTrue(attrs.stdout.startswith("0081;"), attrs.stderr)
            with self.assertRaises(ValueError):
                transfer.prepare_output_dir(out)
            # Names that differ only in case would collide on macOS: refused before writing anything.
            empty = Path(tmp) / "empty"
            with self.assertRaises(ValueError):
                transfer.write_outputs(transfer.prepare_output_dir(empty), [("A.txt", b"1"), ("a.txt", b"2")])
            self.assertFalse(empty.exists())
            # The folder filled up during the run: nothing is merged, and no staging folder is left.
            late = Path(tmp) / "late"
            target = transfer.prepare_output_dir(late)
            late.mkdir()
            (late / "keep.txt").write_text("mine")
            with self.assertRaises(OSError):
                transfer.write_outputs(target, [("new.txt", b"x")])
            target.close()
            self.assertEqual(sorted(p.name for p in late.iterdir()), ["keep.txt"])
            self.assertEqual([p.name for p in Path(tmp).iterdir() if p.name.startswith(".pybox-output-")], [])
            with self.assertRaises(ValueError):
                transfer.prepare_output_dir(Path(tmp) / "late" / "keep.txt")


class LocalImageTests(unittest.TestCase):
    def write(self, tmp, data, mode=0o600):
        path = Path(tmp) / "images.json"
        path.write_text(json.dumps(data))
        os.chmod(path, mode)
        return path

    def test_image_record_is_private_and_strict(self):
        good = dict(version=1, images=dict(data=dict(id=DATA_ID, base=container.IMAGE, recipe_sha256=boxes.recipe_sha256(container.IMAGE))))
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(container, "IMAGES_FILE", self.write(tmp, good)):
                box = container.resolve_box("data", files=True)
                self.assertEqual((box.ref, box.memory, box.files), (DATA_ID, 512 * boxes.MIB, True))
            for name, data, mode in [("public", good, 0o644),
                                     ("bad id", dict(version=1, images=dict(data=dict(good["images"]["data"], id="latest"))), 0o600),
                                     ("other base", dict(version=1, images=dict(data=dict(good["images"]["data"], base="python:3"))), 0o600)]:
                with self.subTest(case=name), mock.patch.object(container, "IMAGES_FILE", self.write(tmp, data, mode)):
                    with self.assertRaises(RuntimeError):
                        container.resolve_box("data")
            stale = dict(version=1, images=dict(data=dict(good["images"]["data"], recipe_sha256="0" * 64)))
            with mock.patch.object(container, "IMAGES_FILE", self.write(tmp, stale)), self.assertRaisesRegex(RuntimeError, "different recipe"):
                container.resolve_box("data")
        with mock.patch.object(container, "IMAGES_FILE", Path("/nonexistent/images.json")):
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                container.resolve_box("data")
            self.assertEqual(container.resolve_box("stdlib").ref, container.IMAGE)

    def test_recipe_pins_every_package_with_a_hash(self):
        lines = [l for l in boxes.recipe_text().splitlines() if l and not l.startswith("#")]
        self.assertTrue(lines)
        for line in lines:
            self.assertRegex(line, r"^[a-z0-9.-]+==\S+ --hash=sha256:[0-9a-f]{64}$")
        self.assertEqual(set(boxes.recipe_packages()), {"numpy", "pandas", "python-dateutil", "six", "tzdata", "matplotlib", "contourpy",
                                                         "cycler", "fonttools", "kiwisolver", "packaging", "pillow", "pyparsing"})


class CustomImageTests(unittest.TestCase):
    LOCK = ("# from uv pip compile --generate-hashes\nrequests==2.32.3 \\\n    --hash=sha256:" + "a" * 64 +
            "\n    # via app\ncertifi==2026.1.1 --hash=sha256:" + "c" * 64 + "\n")

    def test_lock_files_must_be_exact_pins_with_hashes(self):
        self.assertEqual(boxes.check_lock(self.LOCK).splitlines()[0], "requests==2.32.3 --hash=sha256:" + "a" * 64)
        for bad in ["requests\n", "requests==2.32.3\n", "--index-url https://example.org\n", "-e .\n",
                    "x @ https://example.org/x.whl --hash=sha256:" + "a" * 64, "./local.whl\n", "",
                    "a==1 --hash=sha256:" + "a" * 64 + "\nA==2 --hash=sha256:" + "b" * 64, "x" * 70000]:
            with self.subTest(bad=bad[:40]), self.assertRaises(ValueError):
                boxes.check_lock(bad)
        for name in ["Data", "a", "-x", "x_y", "x" * 32, "../x"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                boxes.check_image_name(name)
        self.assertEqual(boxes.make_box("ml", DATA_ID).memory, 512 * boxes.MIB)

    def test_build_saves_a_private_recipe_and_runs_check_it(self):
        def run(argv, timeout):
            args = argv[len(container.PREFIX):]
            ok = dict(returncode=0, timed_out=False, stdout="", stderr="", output_complete=True)
            if args[:2] == ["container", "commit"]:
                ok["stdout"] = DATA_ID + "\n"
            if args[:2] == ["image", "inspect"]:
                ok["stdout"] = DATA_ID + " linux/arm64"
            return True, ok
        sent = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            os.chmod(tmp, 0o700)
            with mock.patch.object(container, "IMAGES_FILE", Path(tmp) / "images.json"), \
                    mock.patch.object(container, "RECIPES", Path(tmp) / "recipes"), \
                    mock.patch.object(runtime_setup, "_run", side_effect=run), mock.patch.object(runtime_setup, "_image_lock", nullcontext), mock.patch.object(container, "_installation_owner", return_value="c" * 32), \
                    mock.patch.object(container, "_capture", side_effect=lambda argv, data, *a, **k: sent.append(data) or
                                      dict(returncode=0, timed_out=False, stdout="", stderr="")):
                entry = runtime_setup.build_image("web", out=lambda *_: None, lock=self.LOCK)
                self.assertEqual(entry["packages"], {"requests": "2.32.3", "certifi": "2026.1.1"})
                self.assertEqual(sent[0], boxes.check_lock(self.LOCK).encode())
                recipe = Path(tmp) / "recipes/web.lock"
                self.assertEqual(oct(recipe.stat().st_mode & 0o777), "0o600")
                box = container.resolve_box("web")
                self.assertEqual((box.ref, box.recipe, box.memory), (DATA_ID, entry["recipe_sha256"], 512 * boxes.MIB))
                recipe.write_text(boxes.check_lock(self.LOCK).replace("2.32.3", "2.32.4"))
                with self.assertRaisesRegex(RuntimeError, "different recipe"):
                    container.resolve_box("web")
                with self.assertRaises(ValueError):
                    runtime_setup.build_image("web2", out=lambda *_: None)
                with self.assertRaises(ValueError):
                    runtime_setup.build_image("data", out=lambda *_: None, lock=self.LOCK)

    def test_cli_rejects_built_in_names_and_bad_locks_before_touching_the_vm(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "x.lock"
            lock.write_text("requests\n")
            for argv in [["image", "build", "data", "--lock", str(lock)], ["image", "build", "web", "--lock", str(lock)]]:
                with self.subTest(argv=argv), mock.patch.object(container, "_guard") as guard, \
                        redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    main(argv)
                guard.assert_not_called()


class EngineRunTests(unittest.TestCase):
    def setUp(self):
        observer = mock.Mock()
        observer.finish.return_value = container.observation.unknown("mocked collector")
        for patcher in [mock.patch.object(container, "_admission", side_effect=nullcontext),
                        mock.patch.object(container, "_Observer", return_value=observer),
                        mock.patch.object(container, "_reconcile_owned", return_value=container.CleanupResult(complete=True, admission_allowed=True)),
                        mock.patch.object(container, "_save_attempt"), mock.patch.object(container, "_clear_attempt"),
                        mock.patch.object(container, "_installation_owner", return_value="c" * 32),
                        mock.patch.object(container, "_guard"), mock.patch.object(container, "_check_policy"),
                        mock.patch.object(container, "resolve_box", side_effect=lambda image, files, moves_files=None: boxes.make_box(image, DATA_ID if image == "data" else container.IMAGE, files, moves_files=moves_files))]:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.observer_class = container._Observer

    def fake_engine(self, program_stdout, transfer=None):
        state = dict(created=None, running=False, removed=False, start=None)

        def capture(argv, input_data, timeout, cap, *, deadline=None):
            args = argv[len(container.PREFIX):]
            out = ""
            if args[:2] == ["container", "create"]:
                labels = dict(args[i + 1].split("=", 1) for i, flag in enumerate(args) if flag == "--label")
                state["created"] = {"Id": "a" * 64, "Name": "/" + args[args.index("--name") + 1], "Config": {"Labels": labels}}
                state["create"] = args
                out = "a" * 64
            elif args[:2] == ["container", "start"]:
                state.update(running=True, start=dict(input=input_data, timeout=timeout, cap=cap))
                out = program_stdout + (transfer or "")
            elif args[:2] == ["container", "inspect"]:
                data = copy.deepcopy(state["created"])
                data["State"] = {"Status": "exited" if state["running"] else "created", "Running": False, "ExitCode": 0,
                                 "Error": "", "OOMKilled": False,
                                 "StartedAt": "2026-10-21T12:00:00Z" if state["running"] else "0001-01-01T00:00:00Z"}
                out = json.dumps(data)
            elif args[:2] == ["container", "rm"]:
                state["removed"] = True
            elif args[:2] == ["container", "ls"] and not state["removed"]:
                out = "a" * 64
            return dict(argv=argv, returncode=0, elapsed_s=0.01, timed_out=False, stdout=out, stderr="",
                        stdout_truncated=False, stderr_truncated=False, output_complete=True, input_complete=True)
        return state, capture

    def test_long_data_run_with_files_frames_input_and_splits_outputs(self):
        with mock.patch.object(container.uuid, "uuid4", return_value=mock.Mock(hex="e" * 32)):
            payload = boxes.MARKER + "e" * 32 + " " + json.dumps(dict(files=[["r.txt", 2]], skipped=[])) + "\n" + base64.b64encode(b"ok").decode() + "\n"
            state, capture = self.fake_engine("printed\n", payload)
            with mock.patch.object(container, "_capture", side_effect=capture):
                result = container.run_container("print(1)", timeout_s=12, image="data", inputs=[("in.csv", b"1,2")], collect_outputs=True)
        self.assertIsNone(result.runner_error)
        self.assertEqual(result.stdout, "printed\n")
        self.assertEqual(result.output_files, (("r.txt", b"ok"),))
        self.assertTrue(state["start"]["input"].startswith(b"PYBOX1 "))
        self.assertEqual(state["start"]["timeout"], 12)
        self.assertEqual(state["start"]["cap"], 65536 + boxes.OUTPUT_WIRE_CAP)
        self.assertIn(DATA_ID, state["create"])
        record = result.record
        self.assertEqual(record["configured"]["image_name"], "data")
        self.assertEqual(record["configured"]["memory_bytes"], 512 * boxes.MIB)
        self.assertEqual(record["files"]["inputs"][0]["name"], "in.csv")
        self.assertEqual(record["files"]["outputs"][0]["bytes"], 2)
        start = [op for op in result.operations if op.get("phase") == "start"][0]
        self.assertNotIn("PYBOX-OUTPUTS", start["stdout"])

    def test_opt_in_runs_use_the_bootstrap_and_linger_but_only_file_runs_grow_scratch(self):
        self.assertFalse(boxes.opt_in("stdlib", False, 2.0))
        self.assertTrue(boxes.opt_in("stdlib", False, 2.5))
        self.assertTrue(boxes.opt_in("data", False, 1.0))
        self.assertEqual(boxes.linger_for(2.0), 0.12)
        self.assertEqual(boxes.linger_for(30.0), 0.75)
        state, capture = self.fake_engine("hi\n")
        with mock.patch.object(container, "_capture", side_effect=capture):
            result = container.run_container("print('hi')", timeout_s=10)
        header = json.loads(state["start"]["input"].split(b"\n", 1)[0][7:])
        self.assertEqual((header["linger"], header["outputs"], header["files"]), (0.3, False, []))
        self.assertIn("/tmp:" + boxes.TMPFS, state["create"])
        self.assertEqual(state["create"][-2:], ["-c", boxes.BOOTSTRAP])
        self.assertEqual(result.record["configured"]["final_reading_linger_s"], 0.3)
        self.assertIsNone(result.record["files"])

    def test_default_run_sends_source_unchanged_and_records_no_files(self):
        state, capture = self.fake_engine("hi\n")
        with mock.patch.object(container, "_capture", side_effect=capture):
            result = container.run_container("print('hi')")
        self.assertEqual(state["start"]["input"], b"print('hi')")
        self.assertEqual(state["start"]["cap"], 65536)
        self.assertIsNone(result.record["files"])
        self.assertEqual(result.record["configured"]["memory_bytes"], 134217728)


class CliTests(unittest.TestCase):
    def result(self, files=(), record=None):
        return container.ContainerResult("container", "42\n", "", 0, 0.05, False, False, False, True, None, "a" * 64, True,
                                         {}, [], record=record or json.loads((HERE.parent / "docs-site/data/replay/m4-normal.json").read_text())["payload"]["record"],
                                         output_files=tuple(files))

    def test_exec_prints_program_output_then_a_receipt_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            program = Path(tmp) / "p.py"
            program.write_text("print(42)\n")
            (Path(tmp) / "in.txt").write_text("x")
            out, err = io.StringIO(), io.StringIO()
            with mock.patch("pybox.__main__.run_container", return_value=self.result([("r.txt", b"r")])) as run, \
                    mock.patch("sys.stdout", out), redirect_stderr(err):
                status = main(["exec", str(program), "--image", "data", "--timeout", "10",
                               "--input", str(Path(tmp) / "in.txt"), "--output", str(Path(tmp) / "out")])
            self.assertEqual(status, 0)
            run.assert_called_once_with("print(42)\n", timeout_s=10.0, max_output_bytes=65536, image="data",
                                        inputs=[("in.txt", b"x")], collect_outputs=True)
            self.assertEqual(out.getvalue(), "42\n")
            self.assertIn("PyBox receipt", err.getvalue())
            self.assertEqual((Path(tmp) / "out/r.txt").read_bytes(), b"r")

    def test_exec_json_prints_only_the_record(self):
        out = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(b"print(42)\n"), encoding="utf-8")
        with mock.patch("pybox.__main__.run_container", return_value=self.result(record={"schema_version": 1})), \
                mock.patch("sys.stdin", stdin), mock.patch("sys.stdout", out):
            self.assertEqual(main(["exec", "-", "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue()), {"schema_version": 1})

    def test_receipt_renders_recorded_runs_with_sources(self):
        for name in ["m4-normal.json", "m4-memory.json", "m4-timeout.json", "m5-file-boundary.json"]:
            data = json.loads((HERE.parent / "docs-site/data/replay" / name).read_text())
            record = data["payload"]["record"]
            with self.subTest(replay=name):
                text = "\n".join(receipt.render(record, color=False))
                for heading in ["From the container engine", "From the Linux kernel", "From the program", "Not known",
                                "yes, before the program started", "128 MiB · 32 processes · 0.5 CPU", "removed and confirmed gone"]:
                    self.assertIn(heading, text)
        timeout = json.loads((HERE.parent / "docs-site/data/replay/m4-timeout.json").read_text())["payload"]["record"]
        self.assertIn("137 (stopped by PyBox at the deadline)", "\n".join(receipt.render(timeout, color=False)))


class McpOptionTests(unittest.TestCase):
    def test_server_sets_ceilings_and_agents_get_files(self):
        args = mcp_policy.validate_arguments(dict(code="pass", timeout_s=20, image="data", return_files=True,
                                                  files=[dict(name="a.csv", content="1,2"), dict(name="b.bin", content="AAE=", encoding="base64")]),
                                             30, ("stdlib", "data"))
        self.assertEqual((args["timeout_s"], args["image"], args["return_files"]), (20.0, "data", True))
        for bad in [dict(timeout_s=20), dict(image="data"), dict(files=[dict(name="../x", content="")]),
                    dict(files=[dict(name="a", content="!", encoding="base64")]), dict(return_files="yes"),
                    dict(files=[dict(name="a", content="x" * (mcp_policy.MAX_MCP_INPUT_BYTES + 1))])]:
            with self.subTest(bad=str(bad)[:50]), self.assertRaises(ValueError):
                mcp_policy.validate_arguments(dict(code="pass", **bad))
        tool = mcp_policy.make_tool(30, ("stdlib", "data"))
        self.assertEqual(tool["inputSchema"]["properties"]["timeout_s"]["maximum"], 30)
        self.assertEqual(tool["inputSchema"]["properties"]["image"]["enum"], ["stdlib", "data"])
        self.assertEqual(mcp_policy.TOOL["inputSchema"]["properties"]["timeout_s"]["maximum"], 2)

    def test_returned_files_are_bounded_text_or_base64(self):
        files = mcp_policy.deliver_outputs([("a.txt", b"hello"), ("b.bin", b"\xff\x00"), ("big.txt", b"x" * 60000)])
        self.assertEqual(files[0]["content"], "hello")
        self.assertEqual(files[1]["encoding"], "base64")
        self.assertIn("omitted", files[2])
        data = dict(schema_version=1, execution={}, delivery={}, files=[dict(name="x", content="y" * 200000)])
        result = mcp_policy.fit_result(data)
        self.assertNotIn("content", result["structuredContent"]["files"][0])

    def test_worker_configuration_is_strict(self):
        self.assertEqual(mcp._worker_config([]), (2.0, ("stdlib",)))
        self.assertEqual(mcp._worker_config(["--max-timeout", "30", "--images", "stdlib,data"]), (30.0, ("stdlib", "data")))
        with self.assertRaises(ValueError):
            mcp._worker_config(["--images", "data"])


class SetupTests(unittest.TestCase):
    def test_data_image_build_records_a_private_entry_and_always_removes_the_builder(self):
        calls = []

        def run(argv, timeout):
            args = argv[len(container.PREFIX):]
            calls.append(args)
            ok = dict(returncode=0, timed_out=False, stdout="", stderr="", output_complete=True)
            if args[:2] == ["container", "commit"]:
                ok["stdout"] = DATA_ID + "\n"
            if args[:2] == ["image", "inspect"]:
                ok["stdout"] = DATA_ID + " linux/arm64"
            return True, ok
        with tempfile.TemporaryDirectory() as tmp:
            images = Path(tmp) / "images.json"
            with mock.patch.object(container, "IMAGES_FILE", images), mock.patch.object(runtime_setup, "_run", side_effect=run), mock.patch.object(runtime_setup, "_image_lock", nullcontext), mock.patch.object(container, "_installation_owner", return_value="c" * 32), \
                    mock.patch.object(container, "_capture", return_value=dict(returncode=0, timed_out=False, stdout="", stderr="")):
                entry = runtime_setup.build_image("data", out=lambda *_: None)
                self.assertEqual(entry["id"], DATA_ID)
                self.assertEqual(oct(images.stat().st_mode & 0o777), "0o600")
                self.assertEqual(container.local_images()["data"]["recipe_sha256"], boxes.recipe_sha256(container.IMAGE))
            self.assertEqual(calls[-1][:3], ["container", "rm", "--force"])
            create = next(c for c in calls if c[:2] == ["container", "create"])
            self.assertIn(container.IMAGE, create)
            calls.clear()
            with mock.patch.object(container, "IMAGES_FILE", Path(tmp) / "none.json"), \
                    mock.patch.object(runtime_setup, "_run", side_effect=run), mock.patch.object(runtime_setup, "_image_lock", nullcontext), mock.patch.object(container, "_installation_owner", return_value="c" * 32), \
                    mock.patch.object(container, "_capture", return_value=dict(returncode=1, timed_out=False, stdout="", stderr="no network")):
                with self.assertRaisesRegex(RuntimeError, "package install failed"):
                    runtime_setup.build_image("data", out=lambda *_: None)
            self.assertEqual(calls[-1][:3], ["container", "rm", "--force"])

    def test_doctor_text_gives_the_next_step(self):
        lines = runtime_setup.doctor_text(dict(platform="ok", tools={}, runtime="ok", vm="Stopped", guard="not running",
                                               images={"data": "not installed (pybox setup --yes --with data)"}))
        text = "\n".join(lines)
        self.assertIn("pybox vm start", text)
        self.assertIn("--with data", text)


if __name__ == "__main__":
    unittest.main()
