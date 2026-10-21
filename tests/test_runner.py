from contextlib import redirect_stderr, redirect_stdout
import ast
import inspect
import io
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from pybox import RunnerError, run_file
from pybox.__main__ import main


ROOT = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pybox-test-")
        self.addCleanup(self.temp.cleanup)
        self.previous_handler = signal.signal(signal.SIGALRM, self.watchdog)
        self.addCleanup(signal.signal, signal.SIGALRM, self.previous_handler)
        self.addCleanup(signal.setitimer, signal.ITIMER_REAL, 0)
        signal.setitimer(signal.ITIMER_REAL, 5)

    def watchdog(self, signum, frame):
        raise TimeoutError("test exceeded its five-second watchdog")

    def script(self, body):
        path = Path(self.temp.name) / "program.py"
        path.write_text("import signal\nsignal.alarm(3)\n" + body, encoding="utf-8")
        return path

    def assert_clean(self, result):
        self.assertIsNone(result.runner_error)
        self.assertTrue(result.group_cleanup_confirmed)
        self.assertTrue(result.output_complete)
        self.assertIsNotNone(result.returncode)

    def assert_child_gone(self, pid):
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_normal_output_pid_and_wall_time(self):
        result = run_file(self.script("print('hello')\n"), unsafe_local=True)
        self.assertEqual(result.stdout, "hello\n")
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.returncode, 0)
        self.assertGreater(result.pid, 0)
        self.assertGreater(result.elapsed_s, 0)
        self.assertLess(result.elapsed_s, 1.5)
        self.assertFalse(result.timed_out)
        self.assertFalse(result.stdout_truncated)
        self.assert_clean(result)

    def test_stderr_and_real_nonzero_code(self):
        result = run_file(
            self.script("import sys\nprint('problem', file=sys.stderr)\nsys.exit(7)\n"),
            unsafe_local=True,
        )
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "problem\n")
        self.assertEqual(result.returncode, 7)
        self.assertFalse(result.timed_out)
        self.assert_clean(result)

    def test_python_exception_is_not_a_runner_error(self):
        result = run_file(self.script("raise RuntimeError('controlled failure')\n"), unsafe_local=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("RuntimeError: controlled failure", result.stderr)
        self.assert_clean(result)

    def test_requires_explicit_opt_in_before_launch(self):
        path = self.script("print('must not launch')\n")
        with mock.patch("pybox.runner.subprocess.Popen") as launch:
            with self.assertRaises(PermissionError):
                run_file(path)
            for value in (False, None, 1, "yes"):
                with self.subTest(value=value), self.assertRaises(PermissionError):
                    run_file(path, unsafe_local=value)
            launch.assert_not_called()

    def test_validates_timeout_before_launch(self):
        path = self.script("pass\n")
        with mock.patch("pybox.runner.subprocess.Popen") as launch:
            for value in (0, -1, 61, float("nan"), float("inf"), True, "2", 10**400):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    run_file(path, unsafe_local=True, timeout_s=value)
            launch.assert_not_called()

    def test_validates_byte_cap_before_launch(self):
        path = self.script("pass\n")
        with mock.patch("pybox.runner.subprocess.Popen") as launch:
            for value in (0, -1, 1048577, True, 1.5, "100"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    run_file(path, unsafe_local=True, max_output_bytes=value)
            launch.assert_not_called()

    def test_validates_file_before_launch(self):
        with mock.patch("pybox.runner.subprocess.Popen") as launch:
            for path in (Path(self.temp.name) / "missing.py", self.temp.name, None):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    run_file(path, unsafe_local=True)
            launch.assert_not_called()

    def test_stdin_is_eof(self):
        result = run_file(self.script("import sys\nprint(repr(sys.stdin.read()))\n"), unsafe_local=True)
        self.assertEqual(result.stdout, "''\n")
        self.assert_clean(result)

    def test_new_session_minimal_environment_and_isolated_python(self):
        with mock.patch.dict(os.environ, {"PYBOX_TEST_SENTINEL": "not-a-secret"}):
            result = run_file(
                self.script(
                    "import json, os, sys\n"
                    "print(json.dumps([os.getpid(), os.getsid(0), os.getpgrp(), "
                    "os.getenv('PYBOX_TEST_SENTINEL'), sys.flags.isolated]))\n"
                ),
                unsafe_local=True,
            )
        pid, sid, pgid, sentinel, isolated = json.loads(result.stdout)
        self.assertEqual((pid, sid, pgid), (result.pid, result.pid, result.pid))
        self.assertIsNone(sentinel)
        self.assertEqual(isolated, 1)
        self.assert_clean(result)

    def test_sleep_timeout(self):
        result = run_file(
            self.script("import time\nprint('ready')\ntime.sleep(3)\n"),
            unsafe_local=True,
            timeout_s=0.2,
        )
        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, -signal.SIGTERM)
        self.assertEqual(result.stdout, "ready\n")
        self.assertLess(result.elapsed_s, 1.5)
        self.assert_clean(result)

    def test_busy_loop_timeout_with_child_alarm(self):
        result = run_file(
            self.script("while True:\n    pass\n"), unsafe_local=True, timeout_s=0.2
        )
        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, -signal.SIGTERM)
        self.assertLess(result.elapsed_s, 1.5)
        self.assert_clean(result)

    def test_sigterm_ignore_escalates_to_sigkill(self):
        result = run_file(
            self.script(
                "import time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "print('ready')\ntime.sleep(3)\n"
            ),
            unsafe_local=True,
            timeout_s=0.2,
        )
        self.assertEqual(result.stdout, "ready\n")
        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertLess(result.elapsed_s, 1.5)
        self.assert_clean(result)

    def test_both_output_streams_are_bounded_and_drained(self):
        result = run_file(
            self.script(
                "import os\nfor _ in range(128):\n"
                "    os.write(1, b'a' * 4096)\n    os.write(2, b'b' * 4096)\n"
            ),
            unsafe_local=True,
            max_output_bytes=1024,
        )
        self.assertEqual(result.stdout, "a" * 1024)
        self.assertEqual(result.stderr, "b" * 1024)
        self.assertTrue(result.stdout_truncated)
        self.assertTrue(result.stderr_truncated)
        self.assertEqual(result.returncode, 0)
        self.assert_clean(result)

    def test_byte_cap_is_applied_before_utf8_decoding(self):
        result = run_file(
            self.script("import os\nos.write(1, '€'.encode('utf-8'))\n"),
            unsafe_local=True,
            max_output_bytes=2,
        )
        self.assertEqual(result.stdout, "\ufffd")
        self.assertTrue(result.stdout_truncated)
        self.assert_clean(result)

    def test_exact_byte_cap_is_not_truncated(self):
        result = run_file(
            self.script("import os\nos.write(1, b'abcd')\n"),
            unsafe_local=True,
            max_output_bytes=4,
        )
        self.assertEqual(result.stdout, "abcd")
        self.assertFalse(result.stdout_truncated)
        self.assert_clean(result)

    def test_malformed_utf8_is_replaced(self):
        result = run_file(
            self.script("import os\nos.write(1, b'\\xffok')\nos.write(2, b'\\xfeerr')\n"),
            unsafe_local=True,
        )
        self.assertEqual(result.stdout, "\ufffdok")
        self.assertEqual(result.stderr, "\ufffderr")
        self.assert_clean(result)

    def child_script(self, wait_parent=False, close_child_pipes=False):
        streams = ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL" if close_child_pipes else ""
        return self.script(
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-I', '-B', '-c', "
            "'import signal, time; signal.alarm(3); time.sleep(3)']" + streams + ")\n"
            "print(child.pid)\n" + ("time.sleep(3)\n" if wait_parent else "")
        )

    def test_normal_exit_cleans_child_holding_both_pipes_open(self):
        result = run_file(self.child_script(), unsafe_local=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.timed_out)
        self.assertLess(result.elapsed_s, 1.5)
        self.assert_clean(result)
        self.assert_child_gone(int(result.stdout.strip()))

    def test_normal_exit_cleans_child_without_inherited_output_pipes(self):
        result = run_file(self.child_script(close_child_pipes=True), unsafe_local=True)
        self.assertEqual(result.returncode, 0)
        self.assert_clean(result)
        self.assert_child_gone(int(result.stdout.strip()))

    def test_timeout_cleans_same_group_child(self):
        result = run_file(self.child_script(wait_parent=True), unsafe_local=True, timeout_s=0.2)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, -signal.SIGTERM)
        self.assertLess(result.elapsed_s, 1.5)
        self.assert_clean(result)
        self.assert_child_gone(int(result.stdout.strip()))

    def test_launch_error_is_distinct(self):
        with mock.patch("pybox.runner.subprocess.Popen", side_effect=OSError("controlled launch failure")):
            with self.assertRaisesRegex(RunnerError, "could not launch Python"):
                run_file(self.script("pass\n"), unsafe_local=True)

    def test_collection_error_still_reaps_and_closes_pipes(self):
        real_launch = subprocess.Popen
        launched = []

        def launch(*args, **kwargs):
            process = real_launch(*args, **kwargs)
            launched.append(process)
            return process

        with mock.patch("pybox.runner.subprocess.Popen", side_effect=launch):
            with mock.patch.object(selectors.DefaultSelector, "select", side_effect=OSError("controlled read failure")):
                result = run_file(self.script("import time\ntime.sleep(3)\n"), unsafe_local=True)
        self.assertIn("output collection failed", result.runner_error)
        self.assertFalse(result.output_complete)
        self.assertTrue(result.group_cleanup_confirmed)
        self.assertIsNotNone(result.returncode)
        self.assertTrue(launched[0].stdout.closed)
        self.assertTrue(launched[0].stderr.closed)

    def test_unconfirmed_group_cleanup_is_reported_honestly(self):
        real_killpg = os.killpg

        def killpg(pgid, sig):
            if sig == 0:
                raise PermissionError("controlled group-probe failure")
            return real_killpg(pgid, sig)

        with mock.patch("pybox.runner.os.killpg", side_effect=killpg):
            result = run_file(self.script("pass\n"), unsafe_local=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.group_cleanup_confirmed)
        self.assertIn("could not be confirmed", result.runner_error)
        self.assertTrue(result.output_complete)
        self.assertLess(result.elapsed_s, 1.5)

    def test_unfinished_output_drain_is_bounded(self):
        def stalled_select(selector, timeout=None):
            time.sleep(timeout)
            return []

        with mock.patch.object(selectors.DefaultSelector, "select", stalled_select):
            result = run_file(self.script("print('controlled output')\n"), unsafe_local=True)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.group_cleanup_confirmed)
        self.assertFalse(result.output_complete)
        self.assertIn("did not reach EOF", result.runner_error)
        self.assertLess(result.elapsed_s, 1.5)

    def test_interruption_still_reaps_and_closes_pipes(self):
        real_launch = subprocess.Popen
        real_select = selectors.DefaultSelector.select
        launched = []
        interrupted = False

        def launch(*args, **kwargs):
            process = real_launch(*args, **kwargs)
            launched.append(process)
            return process

        def select_once_interrupted(selector, timeout=None):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            return real_select(selector, timeout)

        with mock.patch("pybox.runner.subprocess.Popen", side_effect=launch):
            with mock.patch.object(selectors.DefaultSelector, "select", select_once_interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    run_file(self.script("import time\ntime.sleep(3)\n"), unsafe_local=True)
        self.assertIsNotNone(launched[0].returncode)
        self.assertTrue(launched[0].stdout.closed)
        self.assertTrue(launched[0].stderr.closed)

    def test_first_interruption_during_cleanup_still_escalates_and_reaps(self):
        self.assert_guarded_cleanup_interrupt("loop")

    def test_first_interruption_at_cleanup_entry_still_escalates_and_reaps(self):
        self.assert_guarded_cleanup_interrupt("entry")

    def test_first_cleanup_clock_interrupt_preserves_established_budget(self):
        self.assert_guarded_cleanup_interrupt("clock")

    def test_first_postlaunch_setup_interrupt_still_escalates_and_reaps(self):
        self.assert_guarded_cleanup_interrupt("setup")

    def assert_guarded_cleanup_interrupt(self, phase):
        real_launch = subprocess.Popen
        real_select = selectors.DefaultSelector.select
        real_killpg = os.killpg
        real_monotonic = time.monotonic
        real_set_blocking = os.set_blocking
        source_lines, source_start = inspect.getsourcelines(run_file)
        cleanup_entry_line = next(
            node.lineno + source_start - 1
            for node in ast.walk(ast.parse("".join(source_lines)))
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "cleanup_started" for target in node.targets)
            and isinstance(node.value, ast.Call)
        )
        launched = []
        term_sent = False
        interrupts = 0
        origins = []
        interruption = KeyboardInterrupt("first interruption during cleanup")

        def launch(*args, **kwargs):
            process = real_launch(*args, **kwargs)
            launched.append(process)
            if phase == "setup":
                with selectors.DefaultSelector() as readiness:
                    readiness.register(process.stdout, selectors.EVENT_READ)
                    self.assertTrue(readiness.select(1))
                    self.assertEqual(process.stdout.readline(), b"ready\n")
            return process

        def killpg(pgid, sig):
            nonlocal term_sent
            result = real_killpg(pgid, sig)
            if sig == signal.SIGTERM:
                term_sent = True
            return result

        def interrupt_cleanup(selector, timeout=None):
            nonlocal interrupts
            if phase == "loop" and term_sent and interrupts == 0:
                interrupts += 1
                raise interruption
            return real_select(selector, timeout)

        def interrupt_clock():
            nonlocal interrupts
            frame = sys._getframe(1)
            while frame is not None and frame.f_code is not run_file.__code__:
                frame = frame.f_back
            if frame is not None:
                origin = frame.f_locals.get("cleanup_started")
                if origin is not None:
                    origins.append(origin)
                at_entry = phase == "entry" and frame.f_lineno == cleanup_entry_line
                after_entry = phase == "clock" and origin is not None
                if interrupts == 0 and (at_entry or after_entry):
                    interrupts += 1
                    raise interruption
            return real_monotonic()

        def interrupt_setup(fd, blocking):
            nonlocal interrupts
            if phase == "setup" and interrupts == 0:
                interrupts += 1
                raise interruption
            return real_set_blocking(fd, blocking)

        path = self.script(
            "import time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "print('ready')\ntime.sleep(1)\n"
        )
        started = real_monotonic()
        try:
            with mock.patch("pybox.runner.subprocess.Popen", side_effect=launch):
                with mock.patch("pybox.runner.os.killpg", side_effect=killpg):
                    with mock.patch.object(selectors.DefaultSelector, "select", interrupt_cleanup):
                        with mock.patch("pybox.runner.time.monotonic", side_effect=interrupt_clock):
                            with mock.patch("pybox.runner.os.set_blocking", side_effect=interrupt_setup):
                                with self.assertRaises(KeyboardInterrupt) as raised:
                                    run_file(path, unsafe_local=True, timeout_s=0.2)
            self.assertIs(raised.exception, interruption)
            self.assertEqual(interrupts, 1)
            self.assertEqual(launched[0].returncode, -signal.SIGKILL)
            self.assertEqual(len(set(origins)), 1)
            self.assertLess(real_monotonic() - started, 1.0)
            with self.assertRaises(ProcessLookupError):
                real_killpg(launched[0].pid, 0)
            self.assertTrue(launched[0].stdout.closed)
            self.assertTrue(launched[0].stderr.closed)
        finally:
            for process in launched:
                try:
                    real_killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=1)
                finally:
                    process.stdout.close()
                    process.stderr.close()

    def test_cli_json_and_success_status(self):
        command = [sys.executable, "-B", "-m", "pybox", "run", str(self.script("print('cli')\n")), "--unsafe-local"]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=4)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["stdout"], "cli\n")
        self.assertEqual(result["returncode"], 0)
        self.assertIsNone(result["runner_error"])

    def test_cli_refuses_without_opt_in(self):
        error = io.StringIO()
        with mock.patch("pybox.runner.subprocess.Popen") as launch:
            with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                main(["run", str(self.script("pass\n"))])
            launch.assert_not_called()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("UNSAFE LOCAL", error.getvalue())

    def test_cli_failure_timeout_and_runner_error_have_distinct_statuses(self):
        cases = (
            ("raise SystemExit(7)\n", [], 1),
            ("import time\ntime.sleep(3)\n", ["--timeout", "0.2"], 124),
        )
        for source, flags, expected in cases:
            with self.subTest(expected=expected), redirect_stdout(io.StringIO()):
                self.assertEqual(main(["run", str(self.script(source)), "--unsafe-local"] + flags), expected)
        with mock.patch("pybox.__main__.run_file", side_effect=RunnerError("controlled launch failure")):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["run", "unused.py", "--unsafe-local"]), 125)


if __name__ == "__main__":
    unittest.main()
