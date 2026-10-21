"""Finite Step 4 regressions. Docker is fake; private state uses temporary files."""
import copy
from contextlib import nullcontext
from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from pybox import container
from pybox.__main__ import main


OWNER = "c" * 32
NOW = 1700000200


def fixture(token="b", owner=OWNER, expiry=NOW - 1, running=False):
    identity = dict(name="pybox-step3-" + token * 32, labels={"io.pybox.owner": owner,
                    "io.pybox.run": token * 32, "io.pybox.expires": str(expiry)})
    return dict(Id=token * 64, Name="/" + identity["name"], Config=dict(Labels=identity["labels"]),
                State=dict(Status="running" if running else "created", Running=running, ExitCode=0,
                           StartedAt="0001-01-01T00:00:00Z", FinishedAt="0001-01-01T00:00:00Z", Error="", OOMKilled=False))


class Engine:
    def __init__(self, *objects):
        self.objects = {x["Id"]: x for x in objects}
        self.calls = []
        self.mutate_inspection = None
        self.mutate_result = None
        self.inspections = 0

    def __call__(self, argv, input_data=None, timeout_s=2, cap=65536, *, deadline=None):
        args = argv[len(container.PREFIX):]
        self.calls.append(args)
        verb = args[1]
        out, code = "", 0
        if verb == "ls":
            if "id=" in " ".join(args):
                ids = [x[3:] for x in args if x.startswith("id=")]
                out = "\n".join(cid for cid in ids if cid in self.objects)
            else:
                owner = next(x.split("=", 2)[2] for x in args if x.startswith("label=io.pybox.owner="))
                out = "\n".join(cid for cid, data in self.objects.items() if data["Config"]["Labels"]["io.pybox.owner"] == owner)
        elif verb == "inspect":
            self.inspections += 1
            data = copy.deepcopy(self.objects[args[-1]])
            if self.mutate_inspection:
                self.mutate_inspection(data, self.inspections)
            out = json.dumps(data)
        elif verb == "rm":
            if self.objects[args[-1]]["State"]["Running"]:
                code = 1
            else:
                del self.objects[args[-1]]
        else:
            raise AssertionError(args)
        result = dict(argv=argv, returncode=code, elapsed_s=0.001, timed_out=False, stdout=out, stderr="",
                      stdout_truncated=False, stderr_truncated=False, output_complete=True, input_complete=True)
        if self.mutate_result:
            self.mutate_result(result, verb)
        return result


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for patcher in [mock.patch.object(container, "ROOT", Path(self.temp.name).resolve()),
                        mock.patch.object(container, "_guard"), mock.patch.object(container.time, "time", return_value=NOW),
                        mock.patch.object(container, "_installation_owner", return_value=OWNER)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def reconcile(self, engine):
        with mock.patch.object(container, "_capture", side_effect=engine):
            return container.cleanup_containers()

    def test_expired_stopped_removed_unexpired_and_foreign_survive(self):
        expired, fresh, foreign = fixture(), fixture("d", expiry=NOW + 100), fixture("e", owner="f" * 32)
        engine = Engine(expired, fresh, foreign)
        result = self.reconcile(engine)
        self.assertTrue(result.admission_allowed)
        self.assertEqual(result.removed, [expired["Id"]])
        self.assertEqual([x["status"] for x in result.found], ["REMOVED", "KEPT_UNEXPIRED"])
        self.assertEqual(set(engine.objects), {fresh["Id"], foreign["Id"]})
        self.assertEqual([a for a in engine.calls if a[1] == "rm"], [["container", "rm", expired["Id"]]])
        self.assertFalse(any("kill" in a or "--force" in a for a in engine.calls))

    def test_running_objects_never_removed_and_block_admission(self):
        for expiry in (NOW - 1, NOW + 100):
            engine = Engine(fixture(expiry=expiry, running=True))
            result = self.reconcile(engine)
            self.assertFalse(result.admission_allowed)
            self.assertTrue(engine.objects)
            self.assertFalse(any(a[1] in {"rm", "kill"} for a in engine.calls))

    def test_every_identity_mismatch_and_invalid_expiry_refuses_removal(self):
        mutations = [lambda x: x.update(Id="a" * 64), lambda x: x.update(Name="/foreign"),
                     lambda x: x["Config"]["Labels"].update({"io.pybox.owner": "a" * 32}),
                     lambda x: x["Config"]["Labels"].update({"io.pybox.run": "a" * 32}),
                     lambda x: x["Config"]["Labels"].update({"io.pybox.expires": "NaN"})]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                engine = Engine(fixture())
                engine.mutate_inspection = lambda data, count: mutation(data)
                result = self.reconcile(engine)
                self.assertIsNotNone(result.runner_error)
                self.assertFalse(any(a[1] == "rm" for a in engine.calls))

    def test_second_identity_verification_catches_label_change(self):
        engine = Engine(fixture())
        engine.mutate_inspection = lambda data, count: data["Config"]["Labels"].update({"io.pybox.expires": str(NOW + 100)}) if count == 2 else None
        result = self.reconcile(engine)
        self.assertFalse(result.admission_allowed)
        self.assertFalse(any(a[1] == "rm" for a in engine.calls))

    def test_calendar_rollback_keeps_expired_candidate(self):
        engine = Engine(fixture())
        with mock.patch.object(container.time, "time", side_effect=[NOW, NOW, NOW - 2]):
            result = self.reconcile(engine)
        self.assertIn("clock moved", result.runner_error)
        self.assertTrue(engine.objects)

    def test_incomplete_or_ambiguous_listing_never_removes(self):
        for mutation in [dict(returncode=1), dict(output_complete=False), dict(stdout_truncated=True),
                         dict(stdout="b" * 64 + "\n" + "b" * 64), dict(stdout="short")]:
            with self.subTest(mutation=mutation):
                engine = Engine(fixture())
                engine.mutate_result = lambda result, verb: result.update(mutation) if verb == "ls" else None
                result = self.reconcile(engine)
                self.assertFalse(result.complete)
                self.assertEqual(len(engine.calls), 1)

    def test_ambiguous_attempt_is_retained_then_resolved_by_late_object(self):
        data = fixture()
        identity = dict(name=data["Name"][1:], labels=data["Config"]["Labels"])
        container._save_attempt(identity)
        first = self.reconcile(Engine())
        self.assertFalse(first.admission_allowed)
        self.assertIn("late object", first.runner_error)
        second = self.reconcile(Engine(data))
        self.assertTrue(second.admission_allowed)
        self.assertEqual(second.removed, [data["Id"]])
        self.assertEqual(list(container._attempt_directory().iterdir()), [])

    def test_unacknowledged_attempt_retired_only_on_explicit_request_after_margin(self):
        early = fixture(expiry=NOW - 1)
        identity = dict(name=early["Name"][1:], labels=early["Config"]["Labels"])
        container._save_attempt(identity)
        token = identity["labels"]["io.pybox.run"]
        with mock.patch.object(container, "_capture", side_effect=Engine()):
            implicit = container.cleanup_containers()
            too_soon = container.cleanup_containers([token])
        self.assertFalse(implicit.admission_allowed)
        self.assertIn("late object", implicit.runner_error)
        self.assertFalse(too_soon.admission_allowed)
        self.assertIn("resolution margin", too_soon.runner_error)
        self.assertEqual(len(list(container._attempt_directory().iterdir())), 1)
        container._clear_attempt(identity)
        late = fixture(expiry=NOW - container.RESOLVE_MARGIN_S - 1)
        identity = dict(name=late["Name"][1:], labels=late["Config"]["Labels"])
        container._save_attempt(identity)
        engine = Engine()
        with mock.patch.object(container, "_capture", side_effect=engine):
            resolved = container.cleanup_containers([token])
        self.assertTrue(resolved.admission_allowed)
        self.assertEqual(resolved.pending_attempts[0]["status"], "ABSENT_AFTER_EXPIRY")
        self.assertEqual(list(container._attempt_directory().iterdir()), [])
        query = engine.calls[-1]
        self.assertIn("name=^/" + identity["name"] + "$", query)
        self.assertTrue(all("label=" + k + "=" + v in query for k, v in identity["labels"].items()))
        self.assertFalse(any(a[1] in ("rm", "kill") for a in engine.calls))

    def test_resolve_attempt_rejects_malformed_tokens_before_any_engine_call(self):
        with mock.patch.object(container, "_capture") as capture:
            result = container.cleanup_containers(["../x"])
        self.assertIn("32-hex", result.runner_error)
        capture.assert_not_called()

    def test_cleanup_cli_passes_explicit_resolution_requests(self):
        result = container.CleanupResult(owner=OWNER, complete=True, admission_allowed=True)
        with mock.patch("pybox.__main__.cleanup_containers", return_value=result) as cleanup, mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(main(["cleanup", "--resolve-attempt", "b" * 32]), 0)
        cleanup.assert_called_once_with(["b" * 32])

    def test_interrupt_during_cleanup_is_recorded_and_cleanup_retried_once(self):
        allowed = container.CleanupResult(complete=True, admission_allowed=True)
        with mock.patch.object(container, "_reconcile_owned", return_value=allowed), \
             mock.patch.object(container._Control, "metadata", side_effect=RuntimeError("create failed")), \
             mock.patch.object(container._Control, "cleanup", side_effect=[KeyboardInterrupt(), None]) as cleanup:
            result = container.run_container("pass")
        self.assertEqual(cleanup.call_count, 2)
        self.assertTrue(result.cancelled)
        self.assertIn("cleanup interrupted", result.runner_error)

    def test_journal_failure_before_create_reports_not_attempted(self):
        allowed = container.CleanupResult(complete=True, admission_allowed=True)
        with mock.patch.object(container, "_reconcile_owned", return_value=allowed), \
             mock.patch.object(container, "_save_attempt", side_effect=RuntimeError("disk")), \
             mock.patch.object(container, "_capture") as capture:
            result = container.run_container("pass")
        self.assertEqual(result.cleanup_status, "NOT_ATTEMPTED")
        capture.assert_not_called()

    def test_known_absent_attempt_cleared_with_separate_id_query(self):
        data = fixture()
        container._save_attempt(dict(name=data["Name"][1:], labels=data["Config"]["Labels"]), data["Id"])
        result = self.reconcile(Engine())
        self.assertTrue(result.admission_allowed)
        self.assertEqual(result.pending_attempts[0]["status"], "ABSENT")
        self.assertEqual(len(result.operations), 2)

    def test_journal_id_disagreement_prevents_removal(self):
        data = fixture()
        container._save_attempt(dict(name=data["Name"][1:], labels=data["Config"]["Labels"]), "a" * 64)
        engine = Engine(data)
        result = self.reconcile(engine)
        self.assertFalse(result.admission_allowed)
        self.assertFalse(any(a[1] == "rm" for a in engine.calls))

    def test_bad_journal_cannot_be_overwritten_or_ignored(self):
        path = container._attempt_directory() / ("b" * 32 + ".json")
        path.write_text("{}")
        path.chmod(0o600)
        engine = Engine(fixture())
        result = self.reconcile(engine)
        self.assertFalse(result.complete)
        self.assertEqual(path.read_text(), "{}")
        self.assertEqual(engine.calls, [])

    def test_removal_failure_or_failed_final_query_never_claims_removal(self):
        for phase in ("rm", "ls"):
            engine = Engine(fixture())
            engine.mutate_result = lambda result, verb: result.update(returncode=1) if verb == phase and (verb == "rm" or not engine.objects) else None
            result = self.reconcile(engine)
            self.assertEqual(result.removed, [])
            self.assertFalse(result.admission_allowed)

    def test_single_flight_lock_refuses_overlap_then_releases(self):
        with container._admission():
            with self.assertRaisesRegex(RuntimeError, "holds lifecycle"):
                with container._admission():
                    self.fail("overlap admitted")
        with container._admission():
            pass

    def test_cleanup_cli_reports_without_running_source(self):
        result = container.CleanupResult(owner=OWNER, found=[dict(status="KEPT_UNEXPIRED")], complete=True, admission_allowed=True)
        with mock.patch("pybox.__main__.cleanup_containers", return_value=result), mock.patch("pybox.__main__.run_container") as run, mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(["cleanup"]), 0)
            self.assertEqual(json.loads(output.getvalue()), asdict(result))
            run.assert_not_called()

    def test_failed_reconciliation_blocks_create(self):
        with mock.patch.object(container, "_reconcile_owned", return_value=container.CleanupResult(runner_error="unknown")), mock.patch.object(container, "_capture") as capture:
            result = container.run_container("pass")
        self.assertIn("reconciliation blocks", result.runner_error)
        capture.assert_not_called()

    def test_pending_journal_is_private_and_survives_missing_ack(self):
        data = fixture()
        identity = dict(name=data["Name"][1:], labels=data["Config"]["Labels"])
        with mock.patch.object(container, "_reconcile_owned", return_value=container.CleanupResult(complete=True, admission_allowed=True)), mock.patch.object(container, "_capture", side_effect=RuntimeError("lost ack")):
            result = container.run_container("pass")
        self.assertEqual(result.cleanup_status, "UNCONFIRMED")
        paths = list(container._attempt_directory().iterdir())
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].stat().st_mode & 0o777, 0o600)
        self.assertIsNone(container._read_attempt(paths[0])["container_id"])


class TimerEvidenceTests(unittest.TestCase):
    def test_failed_capture_of_kill_is_retained_as_uncertain_attempt(self):
        control = container._Control(dict(name="pybox-step3-" + "b" * 32,
                         labels=fixture()["Config"]["Labels"]), "b" * 64)
        with mock.patch.object(container, "_guard"), mock.patch.object(container, "_capture", side_effect=OSError("lost response")):
            with self.assertRaises(OSError):
                control.command("kill", ["container", "kill", "--signal=KILL", "b" * 64])
        self.assertEqual(len(control.operations), 1)
        self.assertIn("lost response", control.operations[0]["error"])
        evidence = container._termination_evidence(None, control.operations, 3)
        self.assertTrue(evidence["pybox_kill_attempted"])
        self.assertIsNone(evidence["pybox_kill_sent"])
        self.assertEqual(evidence["mechanism"], "UNKNOWN")

    def test_exact_timer_and_pid_namespace_policy(self):
        data = fixture()
        data["Config"].update(Image=container.IMAGE, User="10000:10000", Tty=False, OpenStdin=True,
                              Entrypoint=["timeout"], Cmd=container._timer_args(0.5))
        data["HostConfig"] = dict(NetworkMode="none", ReadonlyRootfs=True, Privileged=False, Memory=134217728,
                                  MemorySwap=134217728, PidsLimit=32, NanoCpus=500000000, CapDrop=["ALL"],
                                  SecurityOpt=["no-new-privileges"], Tmpfs={"/tmp": container.TMPFS}, LogConfig=dict(Type="none"),
                                  Ulimits=[dict(Name="nofile", Hard=128, Soft=128)], RestartPolicy=dict(Name="no"))
        data["Mounts"] = []
        container._check_policy(data, 0.5)
        self.assertEqual(container._timer_args(0.5), ["-s", "KILL", "1.5", "python", "-I", "-B", "-u", "-"])
        for field, value in [("Init", True), ("PidMode", "host"), ("RestartPolicy", dict(Name="always")),
                             ("CapAdd", ["CHOWN"]), ("Devices", [dict(PathOnHost="/dev/null")]),
                             ("DeviceRequests", [dict(Count=-1)]), ("VolumesFrom", ["foreign"]),
                             ("ExtraHosts", ["host:192.0.2.1"]), ("PublishAllPorts", True)]:
            with self.subTest(field=field), mock.patch.dict(data["HostConfig"], {field: value}), self.assertRaises(RuntimeError):
                container._check_policy(data, 0.5)

    def test_only_observed_timing_and_kill_evidence_are_classified(self):
        state = dict(Status="exited", Running=False, ExitCode=137, Error="", OOMKilled=False,
                     StartedAt="2026-10-19T12:00:00Z", FinishedAt="2026-10-19T12:00:03.02Z")
        evidence = container._termination_evidence(dict(State=state), [], 3)
        self.assertEqual(evidence["mechanism"], "IN_CONTAINER_TIMER_CONSISTENT")
        kill = dict(phase="kill", executed=True, returncode=0, timed_out=False, output_complete=True, start_utc="2026-10-19T12:00:02Z")
        self.assertEqual(container._termination_evidence(dict(State=state), [kill], 3)["mechanism"], "SUPERVISOR_KILL_OBSERVED")
        for mutation in [dict(FinishedAt="2026-10-19T12:00:00.1Z"), dict(OOMKilled=True), dict(StartedAt="0001-01-01T00:00:00Z")]:
            self.assertEqual(container._termination_evidence(dict(State={**state, **mutation}), [], 3)["mechanism"], "UNKNOWN")
        kill["timed_out"] = True
        self.assertEqual(container._termination_evidence(dict(State=state), [kill], 3)["mechanism"], "UNKNOWN")
