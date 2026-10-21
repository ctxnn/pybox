# M3c actual resource results — 19 October 2026

**Nine checks passed in the final attempt.** Thirteen finite containers exercised
memory, process/thread, CPU bandwidth, wall termination and Linux RLIMIT_CPU.
The dedicated VM was explicitly verified **Stopped**; final outcome was saved at
2026-10-19 14:24:03 UTC (19:54 IST). All 19 new containers across four attempts
were removed, no engine KILL was sent, and both original sentinels remain unchanged.
Nothing was committed or pushed. M4 production inspection/provenance is next.

## What changed

- [validate_m3c.py](../tools/validate_m3c.py) runs the fixed comparisons, records
  source snapshots/hashes and enforces runtime, identity, cleanup and stop gates.
- [m3c_observer.sh](../tools/m3c_observer.sh) is a finite trusted guest observer,
  outside the target cgroup. It reads the kernel directly through guarded SSH;
  it neither kills targets nor changes controller settings. The only write is
  the controlled fixture's readiness file in its private `/tmp`.
- [m3c_evidence.py](../tools/m3c_evidence.py) rejects malformed/incomplete frames,
  identity mismatches and counter reversals. Missing fields remain unknown.
- [m3c_fixtures.py](../tools/m3c_fixtures.py) contains finite sources. Shared
  validation policy permits only the explicit 192 MiB, 48-task and one-core
  controls; every unchanged production setting is still inspected.

Production execution code was unchanged by M3c. Its public two-second maximum,
Mac primary deadline and timer PID 1 remain. Measurement fixtures deliberately
use a seven-second wrapper allowance plus the one-second margin, except the
three-second fallback comparison. No keeper replaced PID 1 and no watchdog was
introduced. Validation attaches directly with a bounded outer capture deadline,
bypassing the production Mac primary kill path so resource and guest timer effects
can be observed independently. The inherited validation checkpoint label is still `m3b-fixture`;
full IDs, unique run labels, source snapshots and M3c command records identify
these fixtures independently of that legacy marker.

## Independent evidence and its limits

The guest was Linux **6.8.0-117-generic aarch64**. The observer bound the engine's
guest PID to `/proc/<pid>/cgroup`, exact `/docker/<full ID>` path, canonical path
and stable inode. It checked namespace PID 1, actual timeout/Python command lines,
and that its own cgroup differed. The guarded engine inspected exact full ID,
name, all owner/run/expiry labels, and policy before each fixture operation.
Guest PIDs were never interpreted as Mac PIDs.

All requested counter files were present initially, including `memory.peak`,
`pids.peak`, `cpu.max.burst` and the dotted CPU key `core_sched.force_idle_usec`.
The observed quota period was 100,000 microseconds and burst allowance zero.
Both memory policies had guest `memory.swap.max=0`, all sampled swap use was zero,
and `/proc/swaps` listed no swap devices. This verifies the selected guest's
no-extra-swap configuration; it is not a separate experiment with active VM swap.

Samples are **live, non-atomic observations**. Some last-sample fields disappeared
during teardown in the one-core and sleep cases; their `unavailable` lists are
retained. No unsupported counter was silently replaced with zero, and no sample
is claimed to contain exact final lifetime counters. CPU deltas below exclude
startup before the first sample and work after the last readable sample. The
successful CPU work fixtures slept afterwards so the observer could capture the
work before exit. The OOM fixture's surviving parent similarly allowed post-OOM
reads while preserving the timer as PID 1.

Target output is retained as a separate observation. Kernel metrics come from
the trusted observer, never from Python's printed claims.

## Results

| Check | Actual observations |
| --- | --- |
| Memory/OOM and no extra swap | At 128 MiB: `memory.events` and `.local` increased `oom=1`, `oom_kill=1`; recorded peak **134,217,728 bytes**. The child wait status was -9, while the surviving parent exited 0. Docker marked `OOMKilled=true` despite container exit 0. The 192 MiB control completed the same 160 MiB allocation, had zero OOM events, and peaked at **182,857,728 bytes**. |
| PID controller: processes | Limit 32: 30 children plus Python and timeout reached current/peak 32; six EAGAIN failures matched `pids.events:max +6`. Limit 48: all 36 children succeeded, current/peak 38 and no max events. All children were reaped. |
| PID controller: threads | Limit 32: 30 threads plus Python and timeout reached current/peak 32; six refused starts matched `pids.events:max +6`. Limit 48: all 36 threads succeeded, current/peak 38 and no max events. Threads were joined. The fixed stack size was 1 MiB. |
| CPU bandwidth without killing | Two seconds of compute at quota `50000 100000`: observed CPU delta **1.027607s**, **20 throttled periods**, **0.972228s throttled time**, exit 0. At `100000 100000`: **1.999553s CPU**, zero observed throttled periods, exit 0. Target clocks separately reported ~2.000s work duration in both cases. |
| CPU quota versus wall termination | Under the normal three-second guest fallback, the finite eight-second compute request exited 137 after **3.046069s** engine lifetime; CPU delta **1.446670s**, **28 throttled periods**, no OOM events and Docker OOM false. No engine KILL or outer capture timeout occurred. These controlled observations are consistent with guest timer termination; exit 137 alone would not establish cause. |
| Linux RLIMIT_CPU default | Independent `/proc/<python pid>/limits` readback was soft 1 / hard 2 CPU seconds. Default soft signal: exit **152** (128+Linux SIGXCPU), engine lifetime **2.070602s**, sampled CPU delta **0.911956s**. |
| Linux RLIMIT_CPU handled | Same kernel readback; handler printed its signal and exited **23** after **2.041604s**, sampled CPU delta **0.936366s**. |
| Linux RLIMIT_CPU ignored | Same kernel readback; ignored SIGXCPU, then exit **137** after **4.035814s**, sampled CPU delta **1.924837s**. No OOM, engine KILL or eight-second timer deadline. This is consistent with Linux hard-limit killing in this fixed experiment. The sampled delta is not an exact two-second exit measurement. |
| Linux RLIMIT_CPU sleep | Same kernel readback; the 1.3-second sleep completed, exit **0**, engine lifetime **1.822893s**, sampled CPU delta **0.000324s**. A CPU threshold is distinct from elapsed wall time. |

The Linux ignored-signal outcome differs from M2's measured Mac result: that
finite process exceeded the configured hard value and exited normally. Neither
observation is generalized to every OS/kernel build. Linux RLIMIT_CPU here was
installed by a controlled fixture and independently inspected; this milestone
does not add a production container RLIMIT_CPU feature or prove target-provided
limit installation can be trusted.

## Failed attempts remain failed

| Attempt | Outcome and correction |
| --- | --- |
| 01 | Preflight rejected a new IPv6 `[::1]:4321` listener in addition to Colima's IPv4 management listener. No fixture ran. VM stopped. The next attempt took a fresh complete baseline; no listener exemption or gate weakening was added. |
| 02 | One memory fixture ran and its raw counters captured OOM, but the parser rejected the legitimate dotted `core_sched.force_idle_usec` key. The fixture was removed and VM stopped. Parser syntax and a regression were corrected; the old outcome remains false. |
| 03 | Memory and process checks passed; the thread fixture exited 1 because this guest rejects a 64 KiB stack. All five fixtures were removed and VM stopped. The fixed thread stack was increased to 1 MiB. |
| 04 | Fresh complete run of all nine checks, thirteen fixtures; passed. No prior partial check was substituted into this result. All fixtures removed, both sentinels verified, VM stopped. |

Raw directories: `evidence/raw/pybox-m3c-20261019-01` through `-04`.
Each contains command history, complete captures, selected inspect data and an
outcome. Successful observer parses are also saved as `<fixture>.kernel.json`.
Attempt 03/04 contain full source snapshots; the original sources for 01/02
are separately archived at `evidence/raw/pybox-m3c-initial-sources-20261019`.
External SHA-256 preservation manifests are
`evidence/raw/pybox-m3c-attempt-01-sha256.json` through `-04-sha256.json`.
All failed directories were verified unchanged, and current code/test/harness
hashes matched attempt 04's manifest.

## Final state, validation and next gate

**111 tests passed** with ResourceWarning elevated, in 10.850s. Log:
`evidence/raw/pybox-m3c-final-unit-tests.log`. Counter framing, unavailable values,
identity errors, reversals and undeclared resource changes have regressions.
Shell syntax and all nine generated source variants were parsed before execution.

Final retained foreign ID:
`b0e2b58e7ef153d0f67fa43297ad5970a345ef10c78d3f7efbbac6eb1186bde3`.
Final retained owned ID:
`ba1b9ced0fc5527524d38009fe01f9314b6601a5b4727e682b1c8217ced086c9`.
Both remain created/nonrunning with their exact original identities. The owned
sentinel has expired; this narrow harness intentionally did not invoke owner-wide
reconciliation. An ordinary future run/cleanup can remove that expired owned
object. The foreign object remains ineligible.

Allocated regular files under the dedicated runtime grew from **2,159,665,152**
to **2,197,385,216 bytes**, delta **37,720,064**, across all four attempts
(`st_blocks * 512`; not APFS-exclusive allocation, transfer bytes or virtual
capacity). No install, pull, registry request, Internet comparison, model/provider
spend, image build, persistent observer or new network was introduced. Existing
runtime tools/config/cache/identity/image remain. Raw evidence also occupies local
temporary storage; it is not included in that runtime-tree delta.

For v1, retain aggregate cgroup CPU bandwidth plus wall termination as a coarse
work bound. At 0.5 CPU, rate × two seconds is roughly one CPU second; the
three-second fallback gives roughly 1.5. The observed 100ms quota period,
scheduling and termination latency prevent an exact cumulative ceiling. Do not
add a target-controlled per-process limit as an aggregate substitute.

**M4 next:** integrate a trusted collection lifecycle into normal production runs
and normalize provenance, live-versus-final completeness, unknown counters,
termination evidence and cleanup. This validation observer depends on controlled
fixture readiness and does not yet support arbitrary production source or every
cancellation path. M3c qualification does not claim that API guarantee is shipped.

Mechanism references: [kernel cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
and [Linux getrlimit](https://man7.org/linux/man-pages/man2/getrlimit.2.html).
