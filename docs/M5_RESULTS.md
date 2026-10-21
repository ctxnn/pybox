# M5 actual local stdio MCP results — 19 October 2026

**Thirteen live checks passed in one finite VM pass.** All **139 host tests**
passed with ResourceWarning elevated in **12.574s**, including 17 MCP tests.
All nine new container IDs and the temporary installation file were removed;
both original sentinels remain unchanged. The dedicated VM explicitly ended
**Stopped**. Outcome saved **2026-10-19T15:59:40.209513Z** (21:29 IST).
Changes remain uncommitted pending owner review; no push.

## Implemented interface

[mcp.py](../pybox/mcp.py) implements a pinned **2025-11-25** MCP profile over
newline-delimited JSON-RPC on stdin/stdout, using Python's standard library.
It supports initialization/version negotiation, initialized notification, ping,
tools/list, tools/call and cancellation notifications. It advertises only the
tools capability and one tool, `run_python`. Unknown methods are rejected;
there is no resources, prompts, sampling, HTTP or provider capability.

`run_python` accepts only complete inline `code`, optional `timeout_s` and optional
`max_output_bytes`. [mcp_policy.py](../pybox/mcp_policy.py) enforces UTF-8 source
of at most 65536 bytes, a finite positive wall setting at most 2 seconds, and an
integer per-stream output setting from 1 to 8192 bytes (default 4096). Booleans
are not numbers for these settings. Host paths, shell commands, environment,
backend selection, mounts and Docker options cannot be supplied as parameters.

Every accepted run starts one fixed trusted disposable supervisor with an
isolated interpreter and the engine's clean environment. The worker calls only
`run_container`; it cannot select the unsafe native runner. The existing pinned
image, timer PID 1, resource/restriction policy, journal and engine cleanup stay
unchanged. Server startup/discovery never boots or installs the runtime.

The supervisor's stdout is a separate private pipe. Only validated worker result
frames become MCP responses; target stdout/stderr are nested data in the M4
inspection record. `structuredContent` and serialized JSON text contain the
same record. `delivery` reports reconciliation summarization, diagnostic limits
and additional target-output trimming. The full raw engine evidence is retained
by the qualification harness, outside protocol output.

## Bounds and lifecycle

| Bound | Value |
| --- | --- |
| Active work / queue | One supervisor; no queued calls |
| Session calls / messages | 32 / 256; request IDs cannot be reused |
| Input frame / JSON nesting | 512 KiB / 32 levels |
| Projected record / protocol response | 64 KiB / 256 KiB |
| Pending protocol output / stalled consumer | 1 MiB / close after 5s |
| Trusted worker deadline / cancellation grace | 45s / 22s, whichever expires first |
| Server diagnostics | At most 8 KiB, at most 1024 bytes per diagnostic |

Malformed JSON, duplicate members, nonfinite numbers, excessive nesting, invalid
IDs, arrays and unsupported methods/arguments fail before target execution.
Oversized frames and reused IDs close the session; an incomplete EOF frame
reports a parse error before shutdown. Input/worker/output collection uses a
selector so ping, cancellation and disconnect detection continue during a run.

A cancellation notification suppresses the call response and sends one SIGINT
to the recorded owned Mac supervisor once its signal handler is ready. The
engine then verifies and kills/removes its own target if necessary. EOF, server
SIGINT/SIGTERM, broken output and output stall also cancel active work. A worker
that exceeds its deadline is killed/reaped by exact owned PID, with cleanup
reported **UNCONFIRMED**. The existing timer plus later reconciliation contract
still applies if a supervisor cannot complete cleanup. An internal worker protocol
fault returns a tool error; it is not silently classified as client cancellation.

## Real qualification arrangement

[validate_m5.py](../tools/validate_m5.py) used an independent
[stdio client](../tools/mcp_client.py), with no imports from the protocol server.
It ran the absolute launcher from `/private/tmp`, first while the VM was stopped,
then through the real guarded engine. A harmless host-only file and parent-only
environment canary tested that those particular inputs did not reach the target.

The existing dedicated 2 CPU / 2 GiB runtime passed the unchanged preflight:
same whole-Mac socket baseline for two postboot comparisons, approximately ten
seconds apart; exactly one new IPv4 loopback TCP listener (`127.0.0.1:61442`);
no new unconnected UDP; generated/merged no-share and forwarding rules, actual
guest mounts, private ancestry/context/socket and cached pinned linux/arm64 image.
Connected UDP remains recorded and exempt under the previously accepted rule.

As in M4, the parent held the real installation admission lock. Generated trusted
workers used its outer admission and a private temporary installation UUID file
under runtime/tmp. All other production engine guards, reconciliation, commands,
kernel collection, inspection and cleanup were real. This isolates reconciliation
from the original expired owned sentinel. It does not newly qualify production
lock acquisition or original-owner reconciliation; their earlier tests remain
separate. Stable installation.json was not edited. No target response, engine
readback or kernel counter was mocked in this pass.

## Actual observations

| Check | Observed result |
| --- | --- |
| Offline refusal | MCP initialized while VM Stopped; tool failed with cleanup NOT_ATTEMPTED. VM remained Stopped. |
| Handshake/discovery | Negotiated 2025-11-25; exactly `run_python`, strict argument schema. |
| Invalid requests | Bad JSON, unsupported resource method and four extra/out-of-range argument cases produced errors with zero execution audits. |
| Output as data | Target printed a JSON-RPC-shaped message with ID 999; it appeared only in capture.stdout, never as another protocol response. Target exit 0, cleanup REMOVED. |
| Target failure | Controlled ValueError retained in structured stderr; target exit 1, isError true, cleanup REMOVED. |
| Wall deadline | Requested 0.4s; attach elapsed 0.402211s, engine lifetime **0.435714s**, target 137, no OOM. One acknowledged engine KILL; SUPERVISOR_KILL_OBSERVED, cleanup REMOVED. |
| Escaped output | Finite 32 KiB NUL output per stream, retention cap 8192. Projection was **55,831 bytes**, with both extra trimming flags true. Largest actual MCP response was **120,724 bytes including newline**, below 256 KiB. |
| File/environment boundary | Target saw ENOENT (guest errno 2) for the specific host-only file and no parent-only canary variable; original host file unchanged. |
| Parallel admission | A second call received a busy tool error without being queued; ping answered while the first real target was running. |
| Notification cancellation | Running target was independently inspected first. No cancelled-call response; stderr cleanup REMOVED; raw result cancelled true, one acknowledged engine KILL. |
| EOF cancellation | Closing input while a target ran ended server status 0; cleanup REMOVED. |
| Oversized active input | 524289-byte unterminated frame ended server status 2; active target cleanup REMOVED. |
| Truncated active input | Incomplete JSON followed by EOF produced a parse error and server status 0; active target cleanup REMOVED. |

The four cancellation/shutdown target lifetimes were **0.067096s, 0.066249s,
0.069051s and 0.072311s**, in the order above. Each had cancelled true, target
137, no OOM and one acknowledged exact-ID KILL. Their interrupted capture's
`elapsed_s` remains 0.0 because normal capture return did not assign it; that
field is not substituted for Docker lifetime or cancellation latency. The raw
timestamps and mechanism evidence remain available.

All nine started targets collected resource observations; exact final resource
counters and cross-clock alignment remain unknown under the M4 contract.
Five KILL commands total were sent by normal engine supervision (one wall and
four cancellations), all acknowledged. **No rescue KILL** was needed. Every
new object had cleanup REMOVED and an engine-side absence check. No Docker
network was created. The final reachable container set was exactly the original
foreign and owned sentinel full IDs, with original labels and created/nonrunning
state. The temporary owner file was removed after inode/content/UID/mode checks.

## Evidence, limits and next milestone

Raw directory: `evidence/raw/pybox-m5-20261019-01`. It contains source snapshots
and 25 source hashes, five protocol transcripts with stderr/status, nine full raw
engine results, selected inspections, complete command history, socket/config/
mount/image gates, allocation snapshots, explicit stop/list and true outcome.
The 130 evidence files are frozen by
`evidence/raw/pybox-m5-attempt-01-sha256.json`. Source hashes match the qualified
implementation/tests/harness. The full host test log is
`evidence/raw/pybox-m5-prelive-unit-tests-final.log`.

Unit tests use benign mock workers in actual stdio subprocesses and are not
Docker enforcement evidence. They additionally cover worker crashes/protocol
faults, forced worker deadlines, duplicated request IDs, fragmented frames,
session limits and a stalled output consumer. The latter uses a shortened test
stall setting. Real VM qualification covered the thirteen cases above, not every
shutdown signal or transport/kernel failure race.

The official MCP SDK is absent and was not installed. No SDK or GUI-client
interoperability was exercised; `examples/mcp-client.json` is a generic local
configuration example, not an application registration. No provider/model calls
or prompt-injection resistance were tested. Clients must treat target output as
untrusted data even though it is safely framed by the transport. Finite fixtures
do not prove safety against arbitrary hostile Python.

Runtime allocated regular files: **2,237,472,768 -> 2,254,684,160 bytes**, delta
**17,211,392** (`st_blocks * 512`; not APFS-exclusive storage, virtual capacity,
download volume or assistant cost). Durable git-ignored evidence storage is separate.
Existing tools, disks, cache, configs, pinned image and stable identity remain.
There were no installs, pulls, registry/provider requests, credentials, host
mounts, public listeners, watchdogs, commits or pushes.

M6's bounded repair/evaluation loop is next. Provider credentials and spending
remain separately gated; no paid evaluation has been performed. M7's Paper
documentation/demo design and requested final model/repository review remain on
the roadmap.

Protocol references: [stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
[lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle),
[tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools),
[cancellation](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation).
