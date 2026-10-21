from contextlib import redirect_stderr, redirect_stdout
import io
import errno
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from pybox import RunnerError, run_file
from pybox.__main__ import main
from pybox.runner import CPU_BOOTSTRAP


class CpuLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pybox-cpu-test-")
        self.addCleanup(self.temp.cleanup)
        previous = signal.signal(signal.SIGALRM, self.watchdog)
        self.addCleanup(signal.signal, signal.SIGALRM, previous)
        self.addCleanup(signal.setitimer, signal.ITIMER_REAL, 0)
        signal.setitimer(signal.ITIMER_REAL, 7)

    def watchdog(self, signum, frame):
        raise TimeoutError("CPU test exceeded seven-second watchdog")

    def script(self, body, name="program.py"):
        path = Path(self.temp.name) / name
        path.write_text("import signal\nsignal.alarm(5)\n" + body, encoding="utf-8")
        return path

    def run_limited(self, body, **kwargs):
        return run_file(self.script(body), unsafe_local=True, cpu_soft_limit_s=1, **kwargs)

    def assert_clean(self, result):
        self.assertIsNone(result.runner_error)
        self.assertTrue(result.output_complete)
        self.assertTrue(result.group_cleanup_confirmed)
        self.assertTrue(result.cpu_limit_installed)
        self.assertEqual(result.cpu_soft_limit_s, 1)
        self.assertEqual(result.cpu_hard_limit_s, 2)

    def finite_compute(self):
        return (
            "import time\nend = time.monotonic() + 3.5\n"
            "for _ in range(100_000_000):\n"
            "    if _ % 10000 == 0 and time.monotonic() >= end:\n"
            "        break\n"
        )

    def test_default_launch_stays_direct(self):
        real_launch = subprocess.Popen
        with mock.patch("pybox.runner.subprocess.Popen", wraps=real_launch) as launch:
            path = self.script("print('default')\n")
            result = run_file(path, unsafe_local=True)
        self.assertEqual(launch.call_args.args[0], [sys.executable, "-I", "-B", "-u", str(path.resolve())])
        self.assertEqual(launch.call_args.kwargs["pass_fds"], ())
        self.assertIsNone(result.cpu_soft_limit_s)
        self.assertIsNone(result.cpu_hard_limit_s)
        self.assertFalse(result.cpu_limit_installed)

    def test_requires_opt_in_with_cpu_request(self):
        with mock.patch("pybox.runner.subprocess.Popen") as launch:
            with self.assertRaises(PermissionError):
                run_file(self.script("pass\n"), cpu_soft_limit_s=1)
            launch.assert_not_called()

    def test_cpu_units_and_range_validated_before_spawn(self):
        with mock.patch("pybox.runner.subprocess.Popen") as launch:
            for value in (True, False, 0, -1, 61, 1.0, 0.1, "1", float("nan"), 10**400):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    run_file(
                        self.script("pass\n"), unsafe_local=True, cpu_soft_limit_s=value
                    )
            launch.assert_not_called()

    def test_upper_budget_boundary(self):
        result = run_file(self.script("pass\n"), unsafe_local=True, cpu_soft_limit_s=60)
        self.assertEqual(result.cpu_soft_limit_s, 60)
        self.assertTrue(result.cpu_limit_installed)
        self.assertIsNone(result.runner_error)

    def test_unsupported_limit_refuses_before_spawn(self):
        with mock.patch("resource.getrlimit", side_effect=OSError("unsupported")):
            with mock.patch("pybox.runner.subprocess.Popen") as launch:
                with self.assertRaisesRegex(RunnerError, "unavailable"):
                    self.run_limited("pass\n")
                launch.assert_not_called()

    def test_limits_are_in_child_not_parent(self):
        before = resource.getrlimit(resource.RLIMIT_CPU)
        result = self.run_limited("import resource\nprint(resource.getrlimit(resource.RLIMIT_CPU))\n")
        self.assertEqual(result.stdout, "(1, 2)\n")
        self.assertEqual(resource.getrlimit(resource.RLIMIT_CPU), before)
        self.assert_clean(result)

    def test_script_argv_import_and_exit_semantics_match_direct_execution(self):
        body = (
            "import json, os, sys\n"
            "print(json.dumps([sys.argv, sys.orig_argv, __name__, __file__, __package__, "
            "__spec__, sys.path, os.getcwd(), sys.flags.isolated, sys.stdin.read()]))\n"
            "print('separate stderr', file=sys.stderr)\nraise SystemExit(7)\n"
        )
        path = self.script(body, "space ' unicode-λ.py")
        direct = run_file(path, unsafe_local=True)
        limited = run_file(path, unsafe_local=True, cpu_soft_limit_s=1)
        self.assertEqual((limited.stdout, limited.stderr, limited.returncode),
                         (direct.stdout, direct.stderr, direct.returncode))
        self.assertEqual(limited.returncode, 7)
        self.assert_clean(limited)

    def test_exceptions_syntax_and_local_import_errors_match_direct_execution(self):
        for body in ("raise RuntimeError('controlled')\n", "if :\n", "import nearby\n"):
            with self.subTest(body=body):
                self.script("value = 1\n", "nearby.py")
                path = self.script(body)
                direct = run_file(path, unsafe_local=True)
                limited = run_file(path, unsafe_local=True, cpu_soft_limit_s=1)
                self.assertEqual(limited.stderr, direct.stderr)
                self.assertEqual(limited.returncode, 1)
                self.assert_clean(limited)

    def test_minimal_environment_session_and_closed_status_fd(self):
        body = (
            "import json, os\n"
            "extra = []\nfor fd in range(3, 64):\n"
            "    try: os.fstat(fd)\n"
            "    except OSError: continue\n"
            "    extra.append(fd)\n"
            "print(json.dumps([os.getpid(), os.getsid(0), os.getpgrp(), dict(os.environ), extra]))\n"
        )
        with mock.patch.dict(os.environ, {"PYBOX_TEST_SENTINEL": "not-a-secret"}):
            result = self.run_limited(body)
        pid, sid, pgid, env, extra = json.loads(result.stdout)
        self.assertEqual((pid, sid, pgid), (result.pid,) * 3)
        self.assertNotIn("PYBOX_TEST_SENTINEL", env)
        self.assertLessEqual(set(env), {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"})
        self.assertEqual(extra, [])
        self.assert_clean(result)

    def injected_bootstrap(self, prefix):
        wrapper = Path(self.temp.name) / "bootstrap.py"
        wrapper.write_text(
            "import os, resource, runpy, signal\nsignal.alarm(5)\n" + prefix +
            "\nrunpy.run_path(" + repr(str(CPU_BOOTSTRAP)) + ", run_name='__main__')\n",
            encoding="utf-8",
        )
        return mock.patch("pybox.runner.CPU_BOOTSTRAP", wrapper)

    def test_setup_failure_is_distinct_and_does_not_run_target(self):
        with self.injected_bootstrap(
            "def fail(*args): raise OSError('controlled setup failure')\nresource.setrlimit = fail"
        ):
            result = self.run_limited("print('TARGET MUST NOT RUN')\n")
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.returncode, 125)
        self.assertFalse(result.cpu_limit_installed)
        self.assertIn("CPU-limit bootstrap failed", result.runner_error)
        self.assertTrue(result.group_cleanup_confirmed)

    def test_readback_mismatch_fails_closed(self):
        with self.injected_bootstrap("resource.getrlimit = lambda *args: (9, 10)"):
            result = self.run_limited("print('TARGET MUST NOT RUN')\n")
        self.assertEqual(result.stdout, "")
        self.assertFalse(result.cpu_limit_installed)
        self.assertIsNotNone(result.runner_error)

    def test_exec_failure_is_not_target_exit_125(self):
        with self.injected_bootstrap(
            "def fail(*args): raise OSError('controlled exec failure')\nos.execv = fail"
        ):
            result = self.run_limited("print('TARGET MUST NOT RUN')\n")
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.returncode, 125)
        self.assertTrue(result.cpu_limit_installed)
        self.assertIsNotNone(result.runner_error)
        ordinary = self.run_limited("print('R')\nraise SystemExit(125)\n")
        self.assertEqual(ordinary.returncode, 125)
        self.assert_clean(ordinary)

    def test_missing_handshake_cannot_be_spoofed_by_stdout_or_exit_code(self):
        wrapper = self.script("print('R')\n", "fake-bootstrap.py")
        with mock.patch("pybox.runner.CPU_BOOTSTRAP", wrapper):
            result = self.run_limited("print('TARGET MUST NOT RUN')\n")
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.cpu_limit_installed)
        self.assertIsNotNone(result.runner_error)

    def test_sleep_outlasts_cpu_budget_with_wall_time_remaining(self):
        result = self.run_limited("import time\ntime.sleep(1.2)\nprint('awake')\n", timeout_s=3)
        self.assertEqual(result.stdout, "awake\n")
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.timed_out)
        self.assertGreater(result.elapsed_s, 1)
        self.assert_clean(result)

    def test_wall_timeout_remains_independent(self):
        result = self.run_limited("import time\ntime.sleep(2)\n", timeout_s=0.2)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.termination_signal, "SIGTERM")
        self.assert_clean(result)

    def test_finite_computation_receives_sigxcpu(self):
        result = self.run_limited(self.finite_compute(), timeout_s=4)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.returncode, -signal.SIGXCPU)
        self.assertEqual(result.termination_signal, "SIGXCPU")
        self.assert_clean(result)

    def test_soft_signal_can_be_handled(self):
        result = self.run_limited(
            "import sys\n"
            "def stop(signum, frame):\n    print('handled soft signal')\n    sys.exit(23)\n"
            "signal.signal(signal.SIGXCPU, stop)\n" + self.finite_compute(), timeout_s=4,
        )
        self.assertEqual(result.returncode, 23)
        self.assertEqual(result.stdout, "handled soft signal\n")
        self.assertIsNone(result.termination_signal)
        self.assert_clean(result)

    def test_soft_limit_may_be_raised_but_hard_ceiling_cannot(self):
        result = self.run_limited(
            "import resource\nresource.setrlimit(resource.RLIMIT_CPU, (2, 2))\n"
            "print(resource.getrlimit(resource.RLIMIT_CPU))\n"
            "try: resource.setrlimit(resource.RLIMIT_CPU, (2, 3))\n"
            "except (ValueError, OSError): print('hard raise refused')\n"
        )
        self.assertEqual(result.stdout, "(2, 2)\nhard raise refused\n")
        self.assert_clean(result)

    def test_observed_hard_value_behavior_on_this_platform(self):
        result = self.run_limited(
            "import resource, time\nsignal.signal(signal.SIGXCPU, signal.SIG_IGN)\n"
            "end = time.monotonic() + 3.5\n"
            "for i in range(200_000_000):\n"
            "    if i % 10000 == 0 and (time.process_time() >= 2.2 or time.monotonic() >= end):\n"
            "        break\n"
            "usage = resource.getrusage(resource.RUSAGE_SELF)\n"
            "print(usage.ru_utime + usage.ru_stime)\n", timeout_s=4,
        )
        self.assertFalse(result.timed_out)
        if sys.platform == "darwin":
            self.assertEqual(result.returncode, 0)
            self.assertGreater(float(result.stdout), 2)
            self.assertIsNone(result.termination_signal)
        else:
            self.assertEqual(result.returncode, -signal.SIGKILL)
            self.assertEqual(result.termination_signal, "SIGKILL")
        self.assert_clean(result)

    def test_arbitrary_sigkill_is_only_signal_evidence(self):
        result = self.run_limited("import os\nos.kill(os.getpid(), signal.SIGKILL)\n")
        self.assertEqual(result.termination_signal, "SIGKILL")
        self.assertFalse(result.timed_out)
        self.assertFalse(hasattr(result, "cpu_exceeded"))
        self.assert_clean(result)

    def test_bounded_output_with_limit(self):
        result = self.run_limited(
            "import os\nfor _ in range(32):\n"
            "    os.write(1, b'a' * 4096)\n    os.write(2, b'b' * 4096)\n",
            max_output_bytes=1024,
        )
        self.assertEqual(result.stdout, "a" * 1024)
        self.assertEqual(result.stderr, "b" * 1024)
        self.assertTrue(result.stdout_truncated and result.stderr_truncated)
        self.assert_clean(result)

    def test_first_interrupt_closes_setup_pipe_and_reaps_child(self):
        launched = []
        pipes = []
        real_fdopen = os.fdopen
        real_launch = subprocess.Popen
        real_select = selectors.DefaultSelector.select
        interrupted = False

        def fdopen(*args, **kwargs):
            pipe = real_fdopen(*args, **kwargs)
            pipes.append(pipe)
            return pipe

        def launch(*args, **kwargs):
            process = real_launch(*args, **kwargs)
            launched.append(process)
            return process

        def interrupt_once(selector, timeout=None):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            return real_select(selector, timeout)

        with mock.patch("pybox.runner.subprocess.Popen", side_effect=launch):
            with mock.patch("pybox.runner.os.fdopen", side_effect=fdopen):
                with mock.patch.object(selectors.DefaultSelector, "select", interrupt_once):
                    with self.assertRaises(KeyboardInterrupt):
                        self.run_limited("import time\ntime.sleep(2)\n")
        self.assertIsNotNone(launched[0].returncode)
        self.assertTrue(launched[0].stdout.closed and launched[0].stderr.closed)
        self.assertEqual(len(pipes), 2)
        self.assertTrue(all(pipe.closed for pipe in pipes))
        with self.assertRaises(ProcessLookupError):
            os.killpg(launched[0].pid, 0)

    def test_launch_failure_closes_control_pipe(self):
        real_fdopen = os.fdopen
        pipes = []

        def fdopen(*args, **kwargs):
            pipe = real_fdopen(*args, **kwargs)
            pipes.append(pipe)
            return pipe

        with mock.patch("pybox.runner.os.fdopen", side_effect=fdopen):
            with mock.patch("pybox.runner.subprocess.Popen", side_effect=OSError("controlled launch failure")):
                with self.assertRaises(RunnerError):
                    self.run_limited("pass\n")
        self.assertEqual(len(pipes), 2)
        self.assertTrue(all(pipe.closed for pipe in pipes))

    def test_first_fdopen_failure_closes_both_raw_descriptors(self):
        self.assert_partial_pipe_cleanup(1, OSError("controlled fdopen failure"))

    def test_second_fdopen_failure_closes_wrapper_and_raw_writer(self):
        self.assert_partial_pipe_cleanup(2, OSError("controlled fdopen failure"))

    def test_partial_pipe_interrupt_closes_descriptors_and_is_reraised(self):
        for failure_at in (1, 2):
            with self.subTest(failure_at=failure_at):
                self.assert_partial_pipe_cleanup(failure_at, KeyboardInterrupt("controlled interrupt"))

    def assert_partial_pipe_cleanup(self, failure_at, failure):
        real_pipe = os.pipe
        real_fdopen = os.fdopen
        real_close = os.close
        fds = []
        wrappers = []
        calls = 0

        def pipe():
            pair = real_pipe()
            fds.extend(pair)
            return pair

        def fdopen(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == failure_at:
                raise failure
            wrapper = real_fdopen(*args, **kwargs)
            wrappers.append(wrapper)
            return wrapper

        expected = KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else RunnerError
        try:
            with mock.patch("pybox.runner.os.pipe", side_effect=pipe):
                with mock.patch("pybox.runner.os.fdopen", side_effect=fdopen):
                    with mock.patch("pybox.runner.os.close", wraps=real_close) as close:
                        with mock.patch("pybox.runner.subprocess.Popen") as launch:
                            with self.assertRaises(expected) as raised:
                                self.run_limited("pass\n")
                            launch.assert_not_called()
            if isinstance(failure, KeyboardInterrupt):
                self.assertIs(raised.exception, failure)
            else:
                self.assertIn("controlled fdopen failure", str(raised.exception))
            self.assertEqual(len(fds), 2)
            self.assertTrue(all(wrapper.closed for wrapper in wrappers))
            self.assertEqual(close.call_args_list, [mock.call(fd) for fd in fds[failure_at - 1:]])
            for fd in fds:
                with self.assertRaises(OSError) as closed:
                    os.fstat(fd)
                self.assertEqual(closed.exception.errno, errno.EBADF)
        finally:
            for wrapper in wrappers:
                wrapper.close()
            for fd in fds:
                try:
                    real_close(fd)
                except OSError as exc:
                    if exc.errno != errno.EBADF:
                        raise

    def test_cli_cpu_option_and_statuses(self):
        path = self.script("print('cli limited')\n")
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["run", str(path), "--unsafe-local", "--cpu-soft-limit", "1"]), 0)
        self.assertTrue(json.loads(output.getvalue())["cpu_limit_installed"])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["run", str(path), "--unsafe-local", "--cpu-soft-limit", "0.5"])
        self.assertEqual(raised.exception.code, 2)
        with self.injected_bootstrap("resource.setrlimit = lambda *args: None"):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["run", str(path), "--unsafe-local", "--cpu-soft-limit", "1"]), 125)


if __name__ == "__main__":
    unittest.main()
