# Step 4 through M6 checkpoint review

Prepared 19 October 2026. **Approval pending: no branch, staging or commits yet.**

Base: `checkpoint/m3a-step3` at
`1e07a74c7fe202c89fc11143a66db7a5b84efe9e`.
The Step 3 definite-create-rejection to NOT_CREATED fix is already committed in
that HEAD. Proposed new branch: `codex/checkpoints-step4-m6`. No push.

This review includes untracked implementation, tests and tools as well as
tracked modifications. A plain `git diff HEAD` omits much of the completed work.
The proposed sequence is six milestone checkpoints and one shared documentation
and archive checkpoint. Patches and complete file/hash inventories are in
[the review directory](../evidence/review), with
[the machine-readable plan](../evidence/review/checkpoint-plan.json).

| Checkpoint | Files changed | Added / removed lines | Fresh offline tests |
| --- | ---: | ---: | ---: |
| Step 4 | 8 | +1,013 / -21 | 104 passed |
| M3b | 8 | +866 / -1 | 106 passed |
| M3c | 7 | +669 / -0 | 111 passed |
| M4 | 12 | +902 / -11 | 122 passed |
| M5 | 11 | +1,165 / -0 | 139 passed |
| M6 | 8 | +979 / -0 | 158 passed |
| Shared documentation and archive | 12 | +2,231 / -8 | Current tree: 158 passed |

Counts are successive snapshot deltas; a shared file can appear in multiple
milestones. Historical qualification results below come from preserved dated
evidence. The fresh tests are offline unit suites with ResourceWarning treated
as an error; they are not reruns of the VM or provider experiments.
All seven patches were applied in sequence to a scratch copy and verified
against their planned snapshot hashes, without using the real Git index.
[Patch verification report](../evidence/review/patch-validation.json).

## 1. Step 4: deadlines and reconciliation

Proposed title: `feat: add timer-backed execution and exact reconciliation (Step 4)`.

- Adds `timeout -s KILL <wall + 1s> python -I -B -u -` as PID 1 while keeping the
  Mac deadline primary. Mechanism reporting uses recorded kill attempts and
  engine state/timestamps, with uncertainty retained.
- Adds admission locking, a private write-ahead attempt journal, next-run
  reconciliation and `pybox cleanup`. Removal requires expired, stopped,
  installation-owned containers with full identity verification.
- Preserved live results include SIGKILL during execution, after CREATE before
  START, and after CREATE before acknowledgement; the timer ended execution,
  stopped leftovers remained, later expiry cleanup reclaimed them, and sentinels
  survived. No watchdog or rescue kill.

Files: `pybox/__init__.py`, `pybox/__main__.py`, `pybox/container.py`,
`tests/test_container.py`, `tests/test_container_lifecycle.py`,
`tests/test_step4.py`, `tools/validate_step4.py`, `docs/STEP4_RESULTS.md`.

[Review patch](../evidence/review/01-step4.patch).
All 11 entries in the recorded Step 4 source-hash manifest match the reconstructed
source snapshot exactly. The results document uses relocated evidence paths.

## 2. M3b: effective restrictions

Proposed title: `feat: harden verified container restrictions (M3b)`.

Rejects unexpected added capabilities, devices/device requests, inherited
volumes, extra hosts and published ports in effective readback. Adds finite
restriction fixtures and a common runtime validation helper. Preserved evidence
covers 13 checks, including source sending SIGTERM/SIGSTOP to PID 1, filesystem,
scratch, network, capabilities, seccomp, no-new-privileges, nofile and logs.

Files: `pybox/container.py`, `tests/test_step4.py`,
`tests/test_validation_policy.py`, `tools/m3b_fixtures.py`,
`tools/runtime_validation.py`, `tools/validate_m3b.py`,
`docs/M3B_PLAN.md`, `docs/M3B_RESULTS.md`.

[Review patch](../evidence/review/02-m3b.patch).
Practical grouping: the shared validation helper is introduced in its current
form, including bounded controls later used by M3c and its durable evidence
input. This is not a claim to reconstruct every historical harness revision.

## 3. M3c: resource qualification

Proposed title: `test: qualify memory task and CPU controls (M3c)`.

Adds observer/fixture evidence for nine finite resource checks: memory/OOM and
peak counters, process/thread task limits, CPU throttling, guest wall timeout and
the separate Linux RLIMIT_CPU experiment. Production engine code is unchanged
from the M3b snapshot. CPU bandwidth is not an exact cumulative CPU budget.

Files: `tests/test_m3c_evidence.py`, `tools/m3c_evidence.py`,
`tools/m3c_fixtures.py`, `tools/m3c_observer.sh`, `tools/validate_m3c.py`,
`docs/M3C_PLAN.md`, `docs/M3C_RESULTS.md`.

[Review patch](../evidence/review/03-m3c.patch).

## 4. M4: trusted inspection

Proposed title: `feat: collect trusted resource inspection records (M4)`.

Adds a finite trusted guest collector armed before START, cgroup identity binding,
versioned inspection records and CLI output. Primary kill/cleanup precedes
waiting for observation. Records distinguish configured/effective policy,
observed counters, output capture, cleanup and unknowns. Preserved live evidence
covers eight cases across three passes; exact final counters and clock alignment
remain unmeasured.

Files: `pybox/__main__.py`, `pybox/container.py`, `pybox/_observe.sh`,
`pybox/observation.py`, `pybox/inspection.py`, `tests/test_container.py`,
`tests/test_container_lifecycle.py`, `tests/test_inspection.py`,
`tools/m4_supervisor.py`, `tools/validate_m4.py`, `docs/M4_PLAN.md`,
`docs/M4_RESULTS.md`.

[Review patch](../evidence/review/04-m4.patch).

## 5. M5: restricted local MCP

Proposed title: `feat: expose restricted local stdio MCP (M5)`.

Adds a bounded local stdio server exposing only `run_python`, isolated owned
supervisors, strict argument/result projection, cancellation and EOF/malformed
input cleanup. No host-shell/path/environment tools or unsafe native fallback.
Preserved evidence covers 13 live checks with an independent client. Official
SDK and GUI interoperability are not established by the example config.

Files: `pybox/__main__.py`, `pybox/_mcp_worker.py`, `pybox/mcp.py`,
`pybox/mcp_policy.py`, `tests/test_mcp.py`, `tools/mcp_client.py`,
`tools/serve_mcp.py`, `tools/validate_m5.py`, `examples/mcp-client.json`,
`docs/M5_PLAN.md`, `docs/M5_RESULTS.md`.

[Review patch](../evidence/review/05-m5.patch).

## 6. M6: bounded repair and comparison

Proposed title: `feat: add bounded NIM repair controller and evaluation (M6)`.

Adds a fixed-profile HTTPS worker, strict full-source proposals, durable budget
reservations, feedback selection, four fixed problems and the comparison driver.
Model output cannot change execution authority or budgets; credentials remain
outside targets. Includes the final null request-fingerprint metadata fix.

Preserved Nemotron results were 4/4 in both groups: basic used five completed
calls and 2,294 reported tokens; structured used four and 11,274. Two earlier
unknown GLM attempts remain charged as reservations. This small fixed oracle
does not establish general superiority. No new API request was made for this
archive/review task.

Files: `pybox/_nim_worker.py`, `pybox/nim.py`, `pybox/repair.py`,
`pybox/repair_cases.py`, `tests/test_repair.py`, `tools/evaluate_m6.py`,
`docs/M6_PLAN.md`, `docs/M6_RESULTS.md`.

[Review patch](../evidence/review/06-m6.patch).

## 7. Shared documentation and durable evidence

Proposed title: `docs: preserve evidence and consolidate project handoff`.

Consolidates README, LEARNING, PROGRESS, roadmap, resource ledger and M7 handoff;
adds this review, the archive index and three offline archive/audit tools; ignores
the evidence directory. Raw evidence itself is retained locally outside Git.
This checkpoint prepares M7; it does not implement or claim M7 completion.
Shared external documents have had their evidence links relocated with backups.

Files: `.gitignore`, `README.md`, `LEARNING.md`, `PROGRESS.md`,
`docs/ROADMAP.md`, `docs/M7_AGENT_HANDOFF.md`,
the runtime installation ledger (kept locally, not published), `docs/EVIDENCE_ARCHIVE.md`,
`docs/CHECKPOINT_REVIEW.md`, `tools/archive_evidence.py`,
`tools/verify_evidence_archive.py`, `tools/audit_secrets.py`.

[Review patch](../evidence/review/07-documentation-archive.patch).
[Archive integrity and credential-scan scope](EVIDENCE_ARCHIVE.md).
The repo/evidence/log scan has no detected credentials. The separate Codex chat
log still contains the user-pasted NVIDIA key; it is not part of this archive.

## Approval boundary

The native runner, CPU bootstrap and their tests match HEAD. Historical refs,
real Git index and working implementation remain intact. The proposed patches
are review artifacts, not staged commits. The VM was not started and no API call
was made. The last preserved runtime evidence reports it Stopped.

On owner approval, create the proposed new branch and seven local checkpoints,
preserving the configured commit signing policy. Keep all evidence local and
git-ignored. Do not push. Recheck the approved snapshot against the working tree
before creating commits if the tree has changed in the meantime.
