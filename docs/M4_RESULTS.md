# M4 actual inspection/collection results — 19 October 2026

**Eight live checks passed in each of three passes; the final code passed all eight in attempt
03.** All 122 host tests passed with ResourceWarning elevated in 10.787s.
All three VM passes explicitly ended **Stopped**. All 24 new containers and all three
temporary validation installation files were removed; the two original sentinels
remain unchanged. Final outcome: 2026-10-19T15:28:48.688910Z (20:58 IST).
Changes remain uncommitted for review. M5 local stdio MCP is next.

## Shipped locally

- `run_container` now returns `resources`, a versioned `record`, and `cancelled`,
  alongside all existing fields. The primary wall deadline still begins immediately
  before START. Its kill/cleanup runs before waiting for collector completion.
- A fixed [guest collector](../pybox/_observe.sh) arms before START and reads the
  exact full-ID cgroup through guarded dedicated Colima SSH. It needs no target
  readiness file or bootstrap, writes nothing in the guest, and preserves timeout
  PID 1. Root's six-second timeout bounds only the collector and its command group;
  the Mac client has an eight-second ceiling. This collector never kills or
  removes target containers and is not a watchdog/reaper.
- [observation.py](../pybox/observation.py) validates bounded frames, canonical
  full-ID binding, inode and independent observer membership. It rejects duplicate
  fields/keys, malformed values, counter reversals and incomplete captures.
  Missing counter reads remain explicit. At most 64 samples and 128 KiB per
  collector stream are retained; malformed/truncated capture yields unavailable
  evidence, never target-derived substitute counters.
- [inspection.py](../pybox/inspection.py) separates requested settings,
  identity-verified effective Docker settings, engine state, live resources,
  untrusted target output, provenance, cleanup and unknowns. Reconciliation omits
  raw command captures in the compact record; detailed operations remain available
  in the backward-compatible raw result.
- `python -B -m pybox container --inspect` emits that record as JSON. Optional
  `--timeout` and `--max-output-bytes` use the existing trusted API bounds. Default
  container output remains the full result. Active-execution SIGINT returns a
  cancelled result after cleanup, with CLI status 130.

No runtime install, image/policy relaxation, public service, MCP server, registry
request, provider API request, key handling, commit or push was added. Native
unsafe execution and its tests remain unchanged from HEAD.

## What the live qualification exercised

[validate_m4.py](../tools/validate_m4.py) used the existing dedicated 2 CPU / 2 GiB
VM, pinned cached image, unfiltered socket baselines/two postboot samples,
no-share/forwarding checks, private configuration and exact endpoint guards.
All execution cases used the real production source, collector, engine commands,
journal, reconciliation, cleanup, result builder and inspection CLI.

The parent held the real installation admission lock. Each pass created a
temporary private installation UUID file in the runtime's tmp directory, and
disposable supervisors used that file and the parent's outer admission. Production
reconciliation therefore queried the isolated validation owner, preserving the
now-expired original owned sentinel. This is an explicit harness arrangement;
it does not claim a new live qualification of the already-tested production lock
acquisition or original-owner reconciliation. No guard, kernel read or engine
response was mocked. Full result files and CLI JSON records were compared exactly.

The policy case deliberately created a **stricter 120 MiB** object, which the
128 MiB production guard rejected before START or collector launch. It was never
executed. The cancellation case sent actual SIGINT to the one recorded live
disposable Mac supervisor after independently inspecting its running owned target.
No broad process signal or rescue KILL was used.

## Final attempt 03 results

| Case | Actual result |
| --- | --- |
| Normal | CLI/target 0; `hello inspection`; one live sample; engine lifetime **0.074583s**. |
| Target error | CLI/target 1; controlled ValueError retained in target stderr; one live sample; **0.079817s** engine lifetime. |
| CPU | CLI/target 0; **11 throttled periods**, **546,997µs throttled time**, sampled CPU delta **560,995µs** during the fixed 1.1s compute plus observation sleep. 22 samples; **1.352158s** engine lifetime. |
| Memory/OOM | CLI/parent 0; bounded child died with wait status -9; independent `memory.events` had **oom=1, oom_kill=1** and recorded peak **134,217,728 bytes**. Docker OOM flag true. 16 samples; **1.008896s** engine lifetime. |
| PID ceiling | CLI/target 0; 30 children created, six failures from 36 attempts; `pids.events:max` increased by **6**. 13 samples; **0.858853s** engine lifetime. |
| Primary wall timeout | Requested 0.4s; attach elapsed **0.402s**, engine lifetime **0.447187s**. CLI 124, container 137, exactly one acknowledged engine KILL; seven samples. Mechanism `SUPERVISOR_KILL_OBSERVED`. |
| Supervisor SIGINT | CLI **130**, cancelled true, container 137; exactly one acknowledged engine KILL, cleanup REMOVED, one live sample. **0.071532s** engine lifetime. Mechanism `SUPERVISOR_KILL_OBSERVED`. |
| Policy rejection | CLI **125**; target status null, no START, no collector, no target output. Effective 120 MiB readback differs from configured 128 MiB. Exact object removed. |

Every collector for a started fixture exited 0 with complete, non-truncated
transport. All seven started cases collected at least one sample without target
cooperation. The policy case correctly reports `NOT_STARTED`, zero samples and
unavailable counters. The normal/error/cancel single-sample deltas are zero
**between samples**, not zero lifetime CPU use.

## Evidence limits remain part of the result

Every record says `final_counters_complete=false`. The memory case retained
post-OOM observations, then a final sample lost reads as the cgroup disappeared;
all those unavailable fields remain in its record. A stopped Docker object does
not preserve live accounting files. Live first/last/max values and between-read
deltas are not exact final lifetime accounting. A short future target can still
finish before a usable sample; that is reported as unavailable.

Clock domains are explicit: Mac UTC/monotonic, Docker guest UTC, and guest uptime.
Their UTC alignment is unmeasured. Attempt 01 acknowledged the timeout/cancellation
KILL commands, but the guest finish timestamps preceded the Mac command-start
timestamps by about 12–14ms. Its mechanism labels remain **UNKNOWN**. We did not
rewrite them or treat acknowledged KILL as proof of synchronized clocks. Attempt
02 had timestamp ordering compatible with `SUPERVISOR_KILL_OBSERVED`. Neither
label is an exact causal proof against every possible race; the raw facts remain
separate from the explanation.

SIGINT qualification covers one interrupt during active execution. Repeated
interrupts and abrupt supervisor death may prevent a completed result record;
the timer/deferred-reclamation contract remains. The new collector does not
persist telemetry after supervisor death, enforce resource limits, or guarantee
all final counters. Admission/expiry reconciliation and the original PID 1
SIGKILL/SIGTERM/SIGSTOP results retain their earlier evidence scope.

## Preservation, cost and next milestone

Raw directories: `evidence/raw/pybox-m4-20261019-01` through `-03`, each with full source
snapshots, hashes, command history, stdout/stderr captures, selected inspections,
eight complete result files, signal evidence and outcome. All three passes are true;
01 predates the explicit clock fields and compact reconciliation; 02 includes them.
Final review then added a lock-protected operation snapshot so a late observer
cannot mutate a returned result. Its regression failed before the fix and passed
afterwards; attempt 03 qualifies that final code. No failed runtime attempt was reclassified.

SHA-256 manifests: `evidence/raw/pybox-m4-attempt-01-sha256.json` through `-03-sha256.json`.
Attempts 01/02 were byte-verified unchanged, and current implementation/test/harness
hashes matched attempt 03. Final host log:
`evidence/raw/pybox-m4-final-verified-unit-tests.log` (122 tests, 10.787s). Earlier development
test logs are preserved separately. Parser, cancellation, arming failure, policy
rejection, transport loss and CLI regressions passed.

Runtime allocated regular files: **2,197,385,216 -> 2,237,472,768 bytes**, delta
**40,087,552** across all three passes (`st_blocks * 512`; not APFS-exclusive allocation,
virtual capacity, transfer bytes or assistant cost). Evidence/source snapshots in
temporary storage are separate. Existing tools, disks, image, configs and stable
installation identity remain; all three temporary validation metadata files are absent.

Final retained IDs are the original foreign
`b0e2b58e7ef153d0f67fa43297ad5970a345ef10c78d3f7efbbac6eb1186bde3`
and owned
`ba1b9ced0fc5527524d38009fe01f9314b6601a5b4727e682b1c8217ced086c9`.
Both remain created/nonrunning with their original labels. No original-owner
cleanup was invoked, and the final reachable container set was exactly these two.

**M5 next:** expose the restricted engine over local stdio MCP, use bounded
inspection records as tool data, keep protocol stdout separate from diagnostics,
and qualify malformed/cancelled protocol calls. No unsafe-native fallback or host
path/shell/backend selector may be exposed.

Mechanism references: [kernel cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html),
[GNU timeout](https://www.gnu.org/software/coreutils/manual/html_node/timeout-invocation.html),
[Docker inspect](https://docs.docker.com/reference/cli/docker/container/inspect/).
