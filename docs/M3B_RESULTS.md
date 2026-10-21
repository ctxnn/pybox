# M3b finite restriction validation — 19 October 2026

**PASS: 13 controlled checks. Dedicated VM explicitly Stopped. No new commit or push.**

The first nine accepted comparisons are source-bound observations from attempt 03. Attempt 04 verified unchanged production/runtime and fixture bindings, then completed networking, output/logging, and PID 1 signal interference. Earlier failed outcomes remain failed and byte-preserved.

## Actual results

| Gate | Protected observation | Finite comparison / scope |
| --- | --- | --- |
| Host boundary | Host canary absent (ENOENT), image file readable, parent-only environment canary absent | No host bind was introduced |
| Read-only root | /var/tmp write failed EROFS | Omitting read-only allowed the same write |
| Scratch capacity | Exactly 16,777,216 bytes before ENOSPC | A 20 MiB tmpfs allowed the fixed 17,825,792-byte write |
| Scratch noexec | Copied /bin/true denied EACCES; actual mount had noexec | Explicit exec permitted it; actual mount omitted noexec |
| Non-root | UID/GID 10000, zero effective/bounding capabilities; /root denied and setuid(0) failed EPERM | Root comparison could list its own /root |
| Capability drop | Even root with CapDrop ALL could not chown its scratch file | Adding only CAP_CHOWN allowed ownership 10001 |
| No-new-privileges | Kernel flag 1; clearing refused EINVAL and remained 1; unprivileged extra all-ALLOW seccomp filter accepted | With flag 0 the extra-filter request failed EACCES; original Docker filter was not removed |
| Default seccomp | Harmless personality(ADDR_NO_RANDOMIZE) failed EPERM; Seccomp=2 | Only seccomp=unconfined succeeded, Seccomp=0 |
| Descriptor cap | EMFILE after 125 extra opens under 128/128; hard-limit increase refused | 192/192 allowed 189 extra opens |
| TCP and synthetic DNS | Both failed ENETUNREACH (Linux errno 101) | Private internal-network fixture returned the TCP canary and DNS NXDOMAIN; no Internet |
| Output retention/logs | 256 KiB per stream retained at 4 KiB per stream; both truncated and drained to EOF; log-none storage delta 20 KiB | Same finite flood with JSON logging grew its container store by 536 KiB |
| PID 1 SIGTERM deadline | Engine lifetime 3.025546s; exit 137, OOMKilled=false, Error empty | Mac primary bypassed, no observer/client rescue KILL, actual /proc/1 timeout readback |
| PID 1 SIGSTOP deadline | Engine lifetime 3.026608s; exit 137, OOMKilled=false, Error empty | Mac primary bypassed, no observer/client rescue KILL, actual /proc/1 timeout readback |

All newly created fixture containers were inspected and removed by exact full ID/name/owner/run/expiry guards, then confirmed absent. The temporary internal bridge networks were checked for exact ID/name/labels, internal mode and empty attachment sets before removal. There were **zero engine KILL commands across all four attempts**.

## Production change and regression checks

The production policy checker now refuses any CapAdd, Devices, DeviceRequests, VolumesFrom, ExtraHosts or PublishAllPorts exposure. Previously these could survive inspection even beside CapDrop ALL. Six negative subcases failed against the old checker and pass after the change. The normal fixed create policy remains unchanged.

106 tests passed with ResourceWarning elevated to errors in 10.846s. New regressions distinguish guest errno names from Mac errno numbers and constrain the baseline capability-name normalization. Full log: `evidence/raw/pybox-m3b-final-unit-tests.log`. Native runner/bootstrap and native/CPU tests remain unchanged.

## Failed harness attempts preserved

| Attempt | Outcome and correction | Runtime cleanup |
| --- | --- | --- |
| 01 | Stopped after three checks: omitting noexec still denied exec. Baseline corrected to explicit exec and kernel mount flags added to observations. | All new fixtures removed; VM stopped; both sentinels survived |
| 02 | Stopped after five checks: Docker returned CAP_CHOWN, while the harness expected CHOWN. Only the deliberately declared baseline capability is now normalized; production rejects either spelling. | One never-started exact fixture was conservatively retained; recovered and removed without START at attempt 03 preflight. VM stopped each time; original sentinels unchanged |
| 03 | Nine checks passed. Network measurements were correct, but the assertion used the Mac ENETUNREACH number against Linux errno 101. Corrected to guest-reported error names with a regression. Original failure was not rewritten. | All new fixtures and network removed; VM stopped; sentinels survived |
| 04 | Completed the four remaining checks after validating source bindings for the nine previous comparisons. | All new fixtures and network removed; VM stopped; sentinels survived |

## Retained objects and resources

The two Step 4 sentinel IDs are unchanged, created/nonrunning and deliberately retained:

- `b0e2b58e7ef153d0f67fa43297ad5970a345ef10c78d3f7efbbac6eb1186bde3`
- `ba1b9ced0fc5527524d38009fe01f9314b6601a5b4727e682b1c8217ced086c9`

The installation-owned sentinel has now expired; this harness intentionally avoided production owner-wide reconciliation to preserve the requested fixture. A later ordinary run/cleanup may remove that expired owned sentinel. Foreign objects remain ineligible. This test did not install a permanent exemption.

Across the four attempts, 45 unique new fixture containers were created and ultimately removed. Two temporary internal networks were created and removed. Runtime allocated regular-file bytes (st_blocks*512) changed from 2,098,147,328 to 2,159,665,152, delta +61,517,824. This includes VM filesystem/engine bookkeeping and is not APFS-exclusive usage or downloaded bytes.

No installs, pulls, registry calls, public ports, host binds, watchdog, M3c exhaustion tests, MCP/agent/provider calls, deployment or Git commit occurred. Existing tools, image, disks/config/cache, installation identity, lifecycle lock and empty attempts directory remain. All original evidence is preserved.

## Limits and interpretation

- These are finite, control-specific comparisons. They do not establish public-hostile-code safety or cover every syscall and interference pattern.
- NNP proof covers kernel state, failed clearing, and extra-filter permission. A setuid-file exec transition was not measured.
- DNS proof uses one actual DNS datagram over UDP to a private fixture resolver, not every libc configuration or Internet resolver.
- Noexec denies direct executable startup from that mount. It does not prevent Python from reading and interpreting a script or imply that arbitrary code execution was eliminated.
- Log storage was measured in the exact container directory before removal. The 20 KiB protected delta is documented bookkeeping noise; it is not a claim of zero whole-VM disk growth.
- The signal fixtures ignored TERM themselves before signalling PID 1 and sleeping eight seconds. Both remained subject to the three-second guest timer. OS/VM pause, kernel failure and other untested interference remain outside these measurements.
- M3c memory/OOM, task/PID and CPU enforcement and trusted counters remain next. No cgroup resource conclusions are inferred from these flags.

## Evidence

- `evidence/raw/pybox-m3b-20261019-01` through `-04`: fresh per-attempt sources, commands, inspect/proc observations, storage measurements, source hashes and outcomes.
- Attempt 04 `outcome.json` combines the nine explicitly source-bound attempt 03 observations with four new observations; `continued_from` records provenance.
- `commands.jsonl` and per-command JSONs prove exact operations, private networking and absence of engine KILL.
- `pid1-sigterm.pid1.json` and `pid1-sigstop.pid1.json` contain actual PID 1 status/cmdline readbacks.
- `owned-stop-list.stdout.txt` in each attempt proves the recorded Stopped status.
- `evidence/raw/pybox-m3b-attempt-01-sha256.json` through `-03-sha256.json` bind the preserved failed attempts. Source/runtime hashes remain matched; installation identity hash is unchanged.

## Mechanism references

- [Linux PID namespaces](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html): PID 1 signal rules; this explains the model, not the live result.
- [GNU timeout 9.7 source](https://github.com/coreutils/coreutils/blob/v9.7/src/timeout.c): monitor handlers and deadline setup.
- [Docker tmpfs options](https://docs.docker.com/engine/storage/tmpfs): explicit mount controls; actual /proc mount flags above establish this VM behavior.
