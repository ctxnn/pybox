"""Portable runtime paths and consent-gated setup. Colima/Docker are fake; files are temporary."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import tempfile
import unittest
from unittest import mock

from pybox import container, runtime_setup


class DerivedPathTests(unittest.TestCase):
    def test_paths_follow_the_current_user(self):
        self.assertEqual(container.HOME, Path.home())
        self.assertEqual(container.USER, pwd.getpwuid(os.getuid()).pw_name)
        self.assertEqual(container.ROOT, Path.home() / ".pybox/runtime")
        self.assertEqual(container.ENV["USER"], container.USER)
        self.assertEqual(container.PREFIX[0], str(container.DOCKER_BIN))

    def test_context_path_is_dockers_sha256_layout(self):
        digest = hashlib.sha256(b"colima-pybox").hexdigest()
        self.assertEqual(digest, "3c51b70754198a5c1a71b5260057aaf9ff7450c979c5a6333fe477095ad06086")
        self.assertEqual(container.CONTEXT, container.DOCKER_CONFIG / "contexts/meta" / digest / "meta.json")

    def test_tools_only_from_allowlist_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory).resolve()
            good = tools / "docker"
            good.write_text("#!/bin/sh\n")
            good.chmod(0o755)
            with mock.patch.object(container, "TOOL_DIRS", (tools,)):
                self.assertEqual(container._check_tool(good), good)
                good.chmod(0o777)
                with self.assertRaisesRegex(RuntimeError, "private executable"):
                    container._check_tool(good)
                with self.assertRaisesRegex(RuntimeError, "missing"):
                    container._check_tool(tools / "colima")
            with self.assertRaisesRegex(RuntimeError, "allowlisted"):
                container._check_tool(good)

    def test_unsupported_platform_fails_closed(self):
        with mock.patch.object(container.sys, "platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "Apple Silicon"):
                container._check_platform()
        with mock.patch.object(container.platform, "machine", return_value="x86_64"):
            with self.assertRaisesRegex(RuntimeError, "Apple Silicon"):
                container._check_platform()

    def test_guard_explains_missing_setup_and_stopped_vm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / ".pybox/runtime"
            with mock.patch.object(container, "_check_tool"), mock.patch.object(container, "_check_platform"), \
                 mock.patch.object(container, "HOME", Path.home()), mock.patch.object(container, "ROOT", root), \
                 mock.patch.object(container, "COLIMA", root / "colima"):
                with self.assertRaisesRegex(RuntimeError, "pybox setup"):
                    container._guard()
                (root / "colima/pybox").mkdir(parents=True)
                with mock.patch.object(container, "CONTEXT", root / "absent.json"):
                    with self.assertRaisesRegex(RuntimeError, "pybox vm start"):
                        container._guard()


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve() / ".pybox/runtime"
        values = dict(ROOT=root, OWNER_FILE=root / "installation.json", COLIMA=root / "colima",
                      LIMA=root / "colima/_lima", DOCKER_CONFIG=root / "docker", SOCKET=root / "colima/pybox/docker.sock")
        values["CONTEXT"] = values["DOCKER_CONFIG"] / "contexts/meta/x/meta.json"
        for name, value in values.items():
            patcher = mock.patch.object(container, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("_check_platform", "_check_tool"):
            patcher = mock.patch.object(container, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = root
        self.calls = []
        self.lines = []
        self.image = [False]

    def fake_run(self, argv, timeout):
        verb = argv[1] if argv[0] == str(container.COLIMA_BIN) else argv[len(container.PREFIX)]
        self.calls.append(verb)
        out = ""
        if verb == "start":
            profile = container.COLIMA / container.PROFILE
            profile.mkdir(mode=0o700)
            (profile / "colima.yaml").write_text("autoActivate: false\nnetwork:\n  address: false\nportForwarder: none\nmounts: null\n")
        if verb == "pull":
            self.image[0] = True
        return True, dict(stdout=out, stderr="", returncode=0)

    def run_setup(self, yes, status=None):
        with mock.patch.object(runtime_setup, "_run", side_effect=self.fake_run), \
             mock.patch.object(runtime_setup, "profile_status", return_value=status), \
             mock.patch.object(runtime_setup, "_image_check", side_effect=lambda: self.image[0]), \
             mock.patch.object(container, "_guard"):
            return runtime_setup.setup(yes, out=self.lines.append)

    def test_dry_run_changes_nothing(self):
        self.assertEqual(self.run_setup(False), 0)
        self.assertFalse(os.path.lexists(self.root.parent))
        self.assertEqual(self.calls, [])
        self.assertTrue(any("Dry run" in line for line in self.lines))
        self.assertTrue(any("~330 MB" in line for line in self.lines))

    def test_yes_creates_private_tree_pulls_pinned_image_and_stops(self):
        self.assertEqual(self.run_setup(True), 0)
        self.assertEqual(self.calls, ["start", "pull", "stop"])
        for path in runtime_setup._dirs():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700, path)
        override = container.LIMA / "_config/override.yaml"
        self.assertEqual(override.read_text(), container.POLICY)
        self.assertEqual(stat.S_IMODE(override.stat().st_mode), 0o600)
        self.assertEqual(json.loads((container.DOCKER_CONFIG / "config.json").read_text()), runtime_setup.DOCKER_CONFIG_DATA)

    def test_existing_profile_is_never_started_or_pulled(self):
        self.assertEqual(self.run_setup(True, status="Stopped"), 0)
        self.assertEqual(self.calls, [])
        self.assertTrue(any("already exists" in line for line in self.lines))

    def test_differing_existing_file_is_a_conflict_and_never_overwritten(self):
        (container.LIMA / "_config").mkdir(parents=True, mode=0o700)
        for path in (self.root.parent, self.root, container.COLIMA, container.LIMA):
            path.chmod(0o700)
        override = container.LIMA / "_config/override.yaml"
        override.write_text("portForwards: []\n")
        override.chmod(0o600)
        self.assertEqual(self.run_setup(True), 2)
        self.assertEqual(override.read_text(), "portForwards: []\n")
        self.assertEqual(self.calls, [])

    def test_failed_verification_still_stops_the_vm(self):
        with mock.patch.object(runtime_setup, "_profile_policy", side_effect=RuntimeError("mounts present")):
            self.assertEqual(self.run_setup(True), 125)
        self.assertEqual(self.calls, ["start", "stop"])

    def test_vm_start_refuses_to_pull_and_stops_on_missing_image(self):
        runtime_setup._create_tree(lambda line: None)
        with mock.patch.object(runtime_setup, "_run", side_effect=self.fake_run), \
             mock.patch.object(runtime_setup, "profile_status", return_value="Stopped"), \
             mock.patch.object(runtime_setup, "_image_check", return_value=False), \
             mock.patch.object(container, "_guard"):
            self.assertEqual(runtime_setup.vm("start", out=self.lines.append), 125)
        self.assertEqual(self.calls, ["start", "stop"])

    def test_doctor_is_read_only(self):
        with mock.patch.object(runtime_setup, "_run", side_effect=self.fake_run), \
             mock.patch.object(runtime_setup, "profile_status", return_value="Stopped"):
            report = runtime_setup.doctor()
        self.assertEqual(self.calls, [])
        self.assertEqual(report["vm"], "Stopped")
        self.assertFalse(os.path.lexists(self.root))


if __name__ == "__main__":
    unittest.main()
