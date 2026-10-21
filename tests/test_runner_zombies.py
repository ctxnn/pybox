"""The native runner and macOS zombie process groups.

macOS answers killpg(pgid, 0) with EPERM, not ESRCH, while a process group holds only
unreaped zombies. That is a normal, brief state after a timeout, and must not be
reported as a failure unless it outlasts the cleanup deadline.
"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from pybox import runner
from pybox.runner import run_file


class ZombieGroupTests(unittest.TestCase):
    def script(self, source):
        folder = tempfile.mkdtemp()
        path = Path(folder) / "program.py"
        path.write_text(source)
        return path

    def test_macos_reports_eperm_for_a_zombie_only_group(self):
        if sys.platform != "darwin":
            self.skipTest("macOS behaviour")
        child = subprocess.Popen(["/bin/sh", "-c", "exit 0"], start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    os.killpg(child.pid, 0)
                except PermissionError:
                    break
                except ProcessLookupError:
                    self.fail("group vanished before it was reaped")
                time.sleep(0.02)
            else:
                self.fail("the exited, unreaped child never left a zombie-only group")
        finally:
            child.wait()
        with self.assertRaises(ProcessLookupError):
            os.killpg(child.pid, 0)

    def test_brief_eperm_after_a_timeout_is_not_an_error(self):
        real = os.killpg
        answers = {"eperm": 3}

        def killpg(pgid, sig):
            if sig == 0 and answers["eperm"] > 0:
                answers["eperm"] -= 1
                raise PermissionError(1, "Operation not permitted")
            return real(pgid, sig)

        with mock.patch.object(runner.os, "killpg", side_effect=killpg):
            result = run_file(self.script("import time\ntime.sleep(5)\n"), unsafe_local=True, timeout_s=0.2)
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.runner_error)
        self.assertEqual(answers["eperm"], 0)

    def test_eperm_that_outlasts_the_deadline_is_still_reported(self):
        real = os.killpg

        def killpg(pgid, sig):
            if sig == 0:
                raise PermissionError(1, "Operation not permitted")
            try:
                return real(pgid, sig)
            except ProcessLookupError:
                raise PermissionError(1, "Operation not permitted")

        with mock.patch.object(runner.os, "killpg", side_effect=killpg), \
                mock.patch.object(runner, "CLEANUP_GRACE_S", 0.5), mock.patch.object(runner, "TERM_GRACE_S", 0.2):
            result = run_file(self.script("import time\ntime.sleep(5)\n"), unsafe_local=True, timeout_s=0.2)
        self.assertIn("process-group check failed", result.runner_error or "")


if __name__ == "__main__":
    unittest.main()
