# Step 4 acceptance results — 19 October 2026

**PASS. Dedicated VM explicitly Stopped. Step 4 remains uncommitted for owner review.**

Actual pass: `2026-10-19T12:33:54.608286+00:00` to `2026-10-19T12:36:26.840780+00:00` (UTC).
Baseline HEAD: `1e07a74c7fe202c89fc11143a66db7a5b84efe9e`, branch `checkpoint/m3a-step3`.
The Step 3 definite-rejection -> NOT_CREATED fix was already in this commit; no additional Step 3 commit was needed.

## Contract and implementation

No watchdog. The requested Mac wall deadline remains primary. PID 1 is GNU timeout with a guest deadline of wall_timeout + one second. Stopped objects may remain until a container run or manual cleanup after expiry. Production expiry stayed 120 seconds; no clock change or shortened production expiry was used.
Current requirements and remaining release gates: [ROADMAP.md](ROADMAP.md).

## Real observations

| Case | Actual observation | Reclamation |
| --- | --- | --- |
| Primary Mac deadline, wall=0.5s, guest fallback=1.5s | Target lifetime 0.565781s; acknowledged PyBox engine KILL; exit 137, OOMKilled=false; controller wall timeout recorded | Exact removal and absence confirmed |
| Supervisor SIGKILL while target runs | Supervisor returncode -9; actual /proc/1 timer PID 1; engine lifetime 3.028433s for guest limit 3s; exit 137, OOMKilled=false; stopped object still existed | Fresh container run after actual expiry |
| Supervisor SIGKILL after acknowledged CREATE/before START | Supervisor returncode -9; created/nonrunning object still existed, StartedAt year 0001; no target execution/exit inferred | Actual python -B -m pybox cleanup after expiry |
| Supervisor SIGKILL after real CREATE/before acknowledgement reaches runner | Supervisor returncode -9; created/nonrunning object still existed, StartedAt year 0001; no target execution/exit inferred | Actual python -B -m pybox cleanup after expiry |

All three supervisors were killed through their acquired process handles, with returncode -9. No Python finally cleanup can explain their removal later. The supervisor command histories contain zero engine KILL commands; the observer command history contains zero engine KILL/rescue commands. The primary Mac timeout is the one separately recorded production KILL.

Before expiry, manual cleanup reported four owned objects, all KEPT_UNEXPIRED, and removed zero. After the running case expired, the next container run removed exactly that leftover before producing `fresh-after-reconciliation\n`. After the two later created cases expired, manual cleanup removed exactly those two objects. Every removal confirmed exact-ID absence. The attempt journal was empty at the end.

The lost-acknowledgement case had container_id=null in the pre-create journal, despite a real engine object. Reconciliation recovered its complete identity from engine inspection; an empty query alone was never treated as noncreation.

## Sentinels deliberately retained

The foreign and unexpired sentinel objects survived every check and were deliberately kept, as requested. Both were created/nonrunning at final inspection. The VM is stopped. The final container set contains exactly these two IDs; this is not a zero-object result. The unexpired sentinel may become eligible on a later invocation after its recorded expiry; the foreign sentinel is never eligible for installation cleanup.

| Sentinel | Full container ID | Expiry (UTC) |
| --- | --- | --- |
| foreign-sentinel | `b0e2b58e7ef153d0f67fa43297ad5970a345ef10c78d3f7efbbac6eb1186bde3` | 2026-10-19T12:34:14+00:00 |
| unexpired-sentinel | `ba1b9ced0fc5527524d38009fe01f9314b6601a5b4727e682b1c8217ced086c9` | 2026-10-19T12:44:15+00:00 |

## Verification and evidence limits

- 104 tests passed with ResourceWarning elevated to errors in 12.156s. Full log: `evidence/raw/pybox-step4-final-unit-tests.log`.
- Actual dedicated-runtime preflight retained the accepted unfiltered whole-Mac TCP/UDP comparisons, ten-second sampling interval, generated/effective no-share/forwarding policy, guest mounts, private context/socket, and pinned cached linux/arm64 image. No install, pull or registry call.
- All production/test/harness hashes still match the pre-live validated-source manifest. Native runner/bootstrap and native/CPU tests are unchanged. Installation metadata hash remains unchanged. HEAD/main/Step 2 refs remain preserved.
- SUPERVISOR_KILL_OBSERVED uses an acknowledged KILL plus coherent engine state/timestamps. IN_CONTAINER_TIMER_CONSISTENT uses no KILL attempt, non-OOM exit 137 and compatible engine lifetime. Neither code output nor exit 137 alone establishes the cause. Arbitrary target self-termination could mimic timer timing.
- This is finite benign parent-death evidence. Target SIGTERM/SIGSTOP against PID 1 remains a deferred M3b release gate. Host/VM pause, kernel failure, timer interference, unbounded daemon latency and exact real-time scheduling are not proved away.

## Retained resources

Runtime allocated regular-file bytes (st_blocks*512): 2,087,821,312 before, 2,098,147,328 after, delta +10,326,016. This is not APFS-exclusive storage, downloaded bytes, or total tooling cost.
New private persistent application state: `~/.pybox/runtime/lifecycle.lock` (0600), `~/.pybox/runtime/attempts/` (0700; empty at final inspection). Pending records were private atomic JSON files and were removed only after confirmed object removal. No watchdog process or service was installed. Existing tools/image/disks/config/cache and the two exact sentinel objects remain.

## Raw artifacts

Fresh immutable pass directory: `evidence/raw/pybox-step4-20261019-implementation-01`. Earlier evidence was not overwritten.

- `outcome.json`: overall result, cases, retained sentinels and runtime allocation.
- `validated-source-hashes.json`: exact uncommitted code/test/harness binding.
- `primary-wall.result.json`, `fresh-run.result.json`, `before-expiry-cleanup.result.json`, `after-expiry-manual-cleanup.result.json`: real API/CLI reports.
- `running/`, `before_start/`, `before_ack/`: supervisor readiness, command histories, signal-9 and engine-state evidence.
- `observer-commands.jsonl`, `production-commands.jsonl`, per-operation command/inspect JSONs: command chronology and absence of rescue KILL.
- `owned-stop-list.stdout.txt`: explicit final Stopped readback.
- `before-state.json`, `after-state.json`: installation resource metadata; no private credential values.

No Step 4 commit, push, PR, merge, install, deployment, M3b interference test or later milestone was performed.
