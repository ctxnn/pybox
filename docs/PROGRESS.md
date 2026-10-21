# Progress

## Released — 0.3.0, 22 October 2026

Public on GitHub (`ctxnn/pybox`), docs at https://ctxnn.github.io/pybox/, and on PyPI as
`pybox-sandbox` (`pipx install pybox-sandbox`; the command is `pybox`). CI is green on
macOS for Python 3.11–3.13. See the "Released" section of [M10_RESULTS.md](M10_RESULTS.md).

## M10 — ready to share, 21 October 2026

matplotlib joined the `data` image; `pybox image build` makes images from your own
hash-locked lock files; opt-in runs pause briefly so the kernel watcher gets a final
reading (a 300 MiB program now shows 327.6 MiB, not 146.8); the watcher connects in 9 ms
instead of 146 ms (0.204 s per full run). Cursor's agent used PyBox over MCP; Claude
Desktop could not be tested from inside itself. An independent review found 2 Medium,
6 Low and 6 Info issues plus 11 doc overclaims; all resolved and re-checked live.
209 tests pass. Committed locally; nothing pushed or published. See
[M10_RESULTS.md](M10_RESULTS.md).

## M9 — useful for real work, 21 October 2026

Approved by the owner and implemented: the `data` image (hash-locked numpy and pandas),
runs up to 30 s, files in and out, `pybox exec` with a readable terminal receipt,
configurable MCP (images, files, server-set ceilings), PyPI-ready packaging under
Apache-2.0 with release and test workflows, a Homebrew template, and `tools/bench.py`.
Checked live in a throwaway installation set up from nothing (3 min 17 s) and then
deleted; the real installation and its sentinels were never touched. 18 live checks
passed, including a headless Claude Code session using PyBox over MCP. A full run takes
0.316 s median. 198 tests pass. Nothing committed, pushed or published. See
[M9_RESULTS.md](M9_RESULTS.md).

## Docs v2 — 21 October 2026

The documentation was rebuilt from scratch at the owner's request, as a combination of
design directions A (a real receipt as the hero) and C (a docs shell with sidebar,
search and dark mode). There are 16 pages in plain language, a landing page, and an
87-second walkthrough of one recorded run, as an in-page player and an MP4 rendered
from the same code. The site is built with the standard library (`docs-site/build.py`).
All links check clean, and the site was viewed at desktop and phone widths in light and
dark. Every program output shown is recorded evidence, labelled as such. Nothing
committed or published.

## Current continuation — M8, 20 October 2026

PyBox is now installable from a clone (`pip install -e .`, `pybox` command)
and no longer hard-coded to one account. Paths derive from the current user,
tools come from a fixed allowlist, and a consent-gated `pybox setup` (dry run
unless `--yes`) creates the dedicated runtime. `pybox vm start|stop|status`
and a read-only `pybox doctor` are new. Code, tools, examples and site carry no
personal paths; historical docs were normalized to `~/`. **176 tests pass.**
Unit-tested only: no VM was started and no second machine has been set up yet.
See [M8_RESULTS.md](M8_RESULTS.md).

## Previous continuation — M7, 20 October 2026

Documentation, docs site, demo package and the final whole-repository review are
delivered; see [M7_RESULTS.md](M7_RESULTS.md). The README has been rewritten
with a prominent one-Mac/one-user caveat. There are a new reference, a ten-chapter
explainer built from LEARNING, and a demo runbook with OFFLINE/REPLAY/LIVE labels
and a recording plan. A static site in `site/` opens on a run inspector over six
recorded runs. Designs are in a Claude design canvas (the Paper exploration was
superseded at the owner's request).

A separate Opus 5.5 session reviewed the whole repository
([M7_FINAL_REVIEW.md](M7_FINAL_REVIEW.md)): 0 Critical, 1 High, 2 Medium.
Fixes: an explicit `pybox cleanup --resolve-attempt` path for unacknowledged
CREATE attempts (the automatic rule is unchanged); a single cleanup retry after
an interrupt; the post-exit inspect gets its own budget; the repair loop accepts
`ABSENT`; plus doc corrections. **164 tests pass.** These code fixes are
unit-tested only; no VM pass was run in M7. The VM stayed Stopped and both
sentinels are untouched. The same reviewer later re-verified
the fixes: all resolved, nothing new above Low. No video was recorded;
nothing was committed, pushed or published.

## Previous continuation — M6, 19 October 2026

The bounded full-source repair controller and finite NVIDIA NIM comparison are
complete locally. The owner authorized GLM first, then choosing another free
model after transport failures. `nvidia/nemotron-3.5-lightning-30b-a3b` completed
all eight sessions: **4/4 repaired** with code + stderr and **4/4** with structured
feedback. Five vs four model requests, respectively; structured feedback consumed
more input tokens. One stderr-group response misstated the allocation size and
added `restart`; strict schema validation rejected it without another execution.
The next model step corrected it. No general superiority is inferred.

There were nine completed NIM calls (13,568 reported tokens) plus two earlier
unconfirmed GLM transport attempts. Their reservations remain held: 11 total
request reservations, 22,528 maximum completion tokens reserved, within the
16-request/32,768-completion-token cap. Unknown usage and settled USD cost are
not zero. Durable admission, two model steps per episode, bounded input/output,
one active operation, no HTTP retries and no host tools are enforced in code.

**158 ResourceWarning-elevated tests pass**, including the post-trial correction
that keeps an unavailable provider fingerprint as JSON null. The real provider
comparison used the preceding 157-test version; only metadata normalization and
its regression changed afterwards, with a separately saved diff. No extra API
call was made for that change. See [M6_RESULTS.md](M6_RESULTS.md).

All **18 new containers** and three temporary owner files across three VM passes
were removed; both original sentinels remain. Each pass explicitly ended Stopped,
final outcome 17:46:00 UTC / 23:16 IST. Exact key scans found no credential in the
source/evidence files. TLS uses the existing macOS CA bundle with verification
enabled; there was no install/pull/paid partner endpoint or public listener.
Native files/refs and all frozen evidence remain preserved. Changes are
uncommitted for review; no push. **M7 is next**, retaining its Paper design and
requested final-model/whole-repository review requirements.

## Previous continuation — M5, 19 October 2026

The stdlib local stdio MCP server exposes only `run_python` through the existing
restricted container engine, pinned to protocol 2025-11-25. Source and settings,
protocol frames, delivery, queue, session counts and worker lifetime are bounded.
Target output remains result data. Cancellation/EOF/shutdown interrupt only the
owned disposable supervisor; that supervisor performs normal engine cleanup.
Discovery never boots the VM and offline execution refuses without fallback.

**139 ResourceWarning-elevated tests passed in 12.574s**, including 17 MCP policy/
protocol tests. **13 real checks passed** in one finite VM pass, using an
independent stdio client, real engine and temporary validation owner/outer lock.
The 0.4s wall case ended after 0.435714s engine lifetime with an acknowledged KILL.
All four active cancellation/shutdown cases returned cleanup REMOVED in diagnostics.
Escaped output stayed bounded (55,831-byte record; largest response 120,724 bytes).
All nine new containers and the temporary owner file were removed, both original
sentinels survived, and the VM explicitly ended Stopped at 15:59:40 UTC / 21:29 IST.
See [M5_RESULTS.md](M5_RESULTS.md) for raw evidence and scope limits.

No SDK was installed; official SDK/GUI interoperability remains untested. No
provider request, credential handling, pull/install or public listener was added.
Native files and preserved Git refs are unchanged. Step 4/M3b/M3c/M4/M5 remain
uncommitted for review; no push. **M6 is next**, with provider spending separately
gated. M7's Paper design/Opus final-review requirements remain on the roadmap.

## Previous continuation — M4, 19 October 2026

M4 now returns trusted live resource observations and a versioned inspection
record; `container --inspect` emits that record. The finite guest collector arms
before START, requires no target readiness/bootstrap, keeps timeout PID 1, and
cannot delay primary kill/cleanup. Source output, configured policy, effective
engine readback, live counters, unknown finals, clock domains and cleanup remain
distinct. Active-execution SIGINT returns cancellation after cleanup, CLI 130.

122 ResourceWarning-elevated tests passed in 10.787s. Eight real production
CLI/collection cases passed in each of three VM passes: normal/error, CPU, OOM,
PID, wall timeout, SIGINT and pre-START policy rejection. The final 0.4s wall case
ended after 0.447187s engine lifetime with an acknowledged KILL. Attempt 01's
cross-clock ordering did not justify its mechanism labels; UNKNOWN was retained.
Final records explicitly mark clock alignment unmeasured and final counters
incomplete. All 24 new containers and all three temporary validation UUID files were
removed; both original sentinels remain. Each VM pass explicitly ended Stopped,
final outcome 15:28:48 UTC / 20:58 IST. See [M4_RESULTS.md](M4_RESULTS.md) for
the isolated-owner/outer-lock harness arrangement, exact evidence and limits.

No new commit/push/install/pull/server/provider request. Native unsafe files remain
unchanged. The final lock-protected operation snapshot prevents late collector mutation. Step 4/M3b/M3c/M4 are uncommitted for owner review. **M5 is next.**

## Previous continuation — M3c, 19 October 2026

M3c's **nine finite resource checks passed** in a fresh final run. Trusted guest
reads captured memory OOM/peak/no-extra-swap configuration, 32-task process and
thread enforcement against 48-task controls, CPU throttling against a one-core
control, separate guest wall termination, and four Linux RLIMIT_CPU cases.
111 ResourceWarning-elevated tests passed in 10.850s. Production runtime code was
unchanged by this milestone. The finite observer retained timeout as PID 1;
normal production collection and normalized provenance remain M4 work.

Three failed attempts are preserved: an additional IPv6 listener failed the
unchanged preflight gate; a valid dotted CPU counter key failed the parser; the
guest rejected a 64 KiB thread stack. The final attempt used a fixed 1 MiB stack
and reran every check. All 19 newly created containers across four attempts were
removed, no engine KILL was issued, and both original sentinels remain unchanged.
Every attempt ended explicitly Stopped; final outcome 14:24:03 UTC / 19:54 IST.
Step 4/M3b/M3c remain uncommitted pending owner review; no push. Actual results,
raw paths, counter limitations and resource ledger:
[docs/M3C_RESULTS.md](M3C_RESULTS.md). **M4 is next.**

## Previous continuation — Step 4 / M3b, 19 October 2026

Step 3, including definite daemon create rejection plus complete empty identity
query -> NOT_CREATED, is already committed locally as `1e07a74` on
`checkpoint/m3a-step3`. The older pending-commit wording below is historical.

The owner accepted the timer plus next-run/manual reconciliation contract and
dropped autonomous zero-object reclamation without another invocation. Step 4
implementation and the bounded supervisor-SIGKILL tests are authorized; a Step 4
commit awaits owner review. No watchdog process. Current roadmap/release gates:
[docs/ROADMAP.md](ROADMAP.md). M3b now includes target SIGTERM/SIGSTOP to PID 1
with the deadline still required; those interference tests are deferred.

Step 4 real acceptance pass **passed**, with the dedicated VM explicitly Stopped.
104 ResourceWarning-elevated tests passed in 12.156s. The primary 0.5s Mac deadline
ended the target via acknowledged engine KILL after 0.565781s. A disposable
supervisor killed with SIGKILL left the three-second timer to end its target after
3.028433s, with no supervisor/observer engine KILL and a retained stopped object.
After actual 120s expiry a fresh run reconciled that object. Manual cleanup later
removed both never-started objects (acknowledged create and lost acknowledgement).
Both sentinels survived and remain deliberately retained. No watchdog, no Step 4
commit, and no further runtime work. Full evidence and limits:
[docs/STEP4_RESULTS.md](STEP4_RESULTS.md).

The subsequent authorized M3b continuation completed **13 finite checks** with
106 ResourceWarning-elevated tests passing in 10.846s. Both PID 1 signal cases
held the 3s deadline (SIGTERM 3.025546s, SIGSTOP 3.026608s) with the Mac primary
bypassed and zero engine KILL commands. Read-only root/scratch, identity/caps,
kernel NNP/seccomp, descriptors, private TCP/synthetic DNS and bounded output/log
comparisons passed. The production inspection guard now rejects added capability,
device, inherited-volume, extra-host and published-port exposure.

Three failed harness attempts remain unchanged: omitted noexec did not request
exec; Docker's CAP_CHOWN spelling differed; a Mac errno constant was compared
with Linux errno 101. One conservatively retained never-started fixture from
attempt 02 was recovered and removed exactly at attempt 03. Attempt 04 verified
unchanged source bindings for nine completed checks and finished the remaining
four. Across all attempts 45 unique new fixture containers and two internal
networks were removed. Original sentinel IDs/labels/states remain unchanged,
including the now-expired owned sentinel. Each VM pass ended explicitly Stopped.
No commit/push, installs, registry, watchdog or M3c/MCP/agent work. Details and
scope limits: [docs/M3B_RESULTS.md](M3B_RESULTS.md). M3c is next.

Current checkpoint: **Step 2 is accepted and signed locally at
`45730cc54d5954b739eb26c6f5e5e7bdc6efb2b9`; all four approved finite Step 3 real
cases passed and were accepted, then the dedicated VM was explicitly verified
Stopped.** The subsequent definite-rejection classification fix is unit-validated
only, with no repeat live pass. Step 3 awaits the displayed cumulative diff and
one separately dispatched signed local checkpoint, not more runtime work.
Its changes remain uncommitted in the main
checkout on `checkpoint/m3a-step2`; the original sibling is historical/untouched.

## Completed locally: milestone 1 — child lifecycle

- Stdlib `run_file` library and JSON CLI with explicit unsafe-local opt-in.
- Separate, concurrently drained, byte-bounded stdout/stderr; real PID, reaped
  return code, monotonic elapsed time, and distinct timeout/runner-error metadata.
- New POSIX session, bounded SIGTERM/SIGKILL cleanup on normal exit and timeout,
  bounded final draining, and honest unconfirmed-cleanup reporting.
- Review fix: establish lifecycle ownership before launch; defer a first interrupt
  in post-launch pipe setup or the coherent cleanup phase, including clock/deadline
  initialization, without overwriting an established origin; re-raise after closure.
- Controlled unittest coverage and two short example programs; no frontend,
  service, AI integration, or dependency installation.

Verification uses `python -B -W error::ResourceWarning -m unittest discover -s tests -v`.
On 2026-10-11, all 31 tests passed locally (`Ran 31 tests in 4.239s`, `OK`),
both CLI examples worked, and guarded cleanup-loop and cleanup-entry probes
confirmed SIGKILL/reaping and closure before the original interrupt was re-raised.
Regressions also check established clock-origin retention and post-launch pipe setup.
Repeated interrupts, interrupted creation before a child handle is acquired, and
abrupt parent death remain outside the supported cleanup coverage.
The working local interpreter is Python 3.11.3 arm64 via `python`; `python3` is
currently unusable (`Bad CPU type in executable`). Files remain uncommitted on
the build Mac. The initial checkout has no commits, and the successful
upstream read advertised no refs; no remote baseline was created.

## Completed locally: milestone 2 — experimental CPU soft threshold

- Optional `cpu_soft_limit_s` / `--cpu-soft-limit` installs per-process RLIMIT_CPU
  `(N, N + 1)` in a trusted child bootstrap, then execs the original interpreter
  command. Omitted behavior remains direct launch; the parent is never limited.
- Separate bounded setup pipe, close-on-exec, fail-closed installation/readback,
  and distinct setup errors. Configured soft/hard fields, installation-only
  metadata, and observed termination signal do not infer CPU cause or usage.
- Scope deliberately narrowed from hard CPU enforcement: on this macOS 27.0.1
  arm64 build, a finite SIGXCPU-ignoring process exceeded the configured hard value
  of 2 CPU seconds and exited normally. Default SIGXCPU termination and catching
  the soft signal work. No non-bypassable cap is offered; wall timeout is independent.
- Finite sleep-versus-computation examples, focused setup/argv/import/traceback/
  signal/output/interruption tests, and an appended ground-up learning chapter.
- No services, installs, frontend, AI, containers, remote execution, commits,
  branches, pushes, or PRs. Existing files and git's unborn-main state are preserved.

Evidence and exact validation results are in
`~/.capy/work/pybox-runtime-02/`; the completion report is
`~/.capy/drive/captain-pybox/reports/PYBO-3-runtime-02.md`.
On 2026-10-15 the full ResourceWarning-elevated suite passed **55/55 tests in
10.711 seconds**: 31 unchanged lifecycle tests plus 24 focused CPU tests. Four
sequential CLI cases matched predictions: ordinary hello (0), short wall-timeout
sleep (124), CPU-option sleep (0), and CPU-option computation (1, SIGXCPU).
The last two took 2.037301 and 1.023556 wall seconds respectively, with no wall
timeout, complete output draining, and confirmed original-group cleanup.

Review correction R2-1 on 2026-10-16: retain both raw setup-pipe descriptors
before building Python wrappers; cleanup chooses each wrapper or its unwrapped
descriptor, never both. First/second wrapping failures and partial-setup interrupts
now have controlled regressions checking OS closure and zero child spawns.
The updated suite passed **58/58 tests in 10.786 seconds** (31 original + 27 CPU
tests), all four CLI cases again matched 0/124/0/1, and the reviewer's exact
partial-init reproduction now reports both descriptors closed in both scenarios.
Evidence: `~/.capy/work/pybox-runtime-02/partial-pipe-fix/`. Independent read-only
revalidation remains the Captain's next step.

## Historical milestone 2 teaching/validation stop

Read the appended milestone 2 chapter in `LEARNING.md`, inspect `_cpu_bootstrap.py`
and `run_file`, and compare the finite sleeping and computing commands. The next
limitation is an actual enforceable resource/isolation boundary, not more host-runner
claims. Further implementation is paused; the Captain independently validates this
milestone and delivers the updated learning page and teaching explanation.

## M3a Step 2 — three real round trips verified (2026-10-18)

The specifically approved retry used the unchanged reviewed backend and a fresh
`~/.capy/work/pybox-runtime-03-step2/retry-connected-udp/` evidence directory.
Only the socket helper's UDP predicate/classification changed: connected `->`
rows stay in the evidence/diff without failing; any new unconnected row fails,
regardless of app/port/IP family. Both postboot pairs against the same baseline
added only TCP `127.0.0.1:55801` and zero UDP rows, about 10.05s apart. Generated/
merged no-share/ignore policy, all 31 guest mounts, private socket ancestry and
the exact local pinned image linux/arm64 query passed, without registry calls.

| Fixture | Observed stdout | Observed stderr | Target exit | Start/attach elapsed |
| --- | --- | --- | --- | --- |
| hi | `"hi\n"` | `""` | 0 | 0.127071s |
| stderr | `""` | `"err\n"` | 0 | 0.055497s |
| exit7 | `""` | `""` | 7 | 0.053848s |

All three trusted State records were exited/nonrunning, Error empty, OOMKilled
false, with real StartedAt/FinishedAt; each fixed defensive setting was read back.
Exact owned removals and final engine-side absence passed before explicit VM
stop. No fourth container, code tweak, extra probe or failure matrix was run.
The existing 64-test result/review below remains valid; unchanged backend tests
were not rerun for this retry. Source is uncommitted; parent/native remain unchanged.

## Historical Step 2 attempt — blocked before fixtures (2026-10-18)

- Added `pybox/container.py`, package exports and the stdin `container` CLI.
  Native `runner.py` and its bootstrap/tests are unchanged; there is no fallback.
- Fixed pinned image/platform, private context/environment, defensive create
  settings, bounded separate streams, inspect-before-removal and exact owned-ID
  cleanup are implemented. Settings are not enforcement proofs.
- Latest full suite: **64/64 tests in 10.605s**, including six mocked container
  cases. One local read-only reviewer found ambiguous-create cleanup and
  engine/target-exit confusion; both were fixed and re-read without remaining
  material findings. No independent live-container validation occurred.
- One unchanged dedicated-profile start succeeded. First comparison added TCP
  `127.0.0.1:55629` and four connected IPv6 UDP rows, so the unchanged no-new-UDP
  rule failed. Raw rows were labeled Helium/Google; names were not filtered and
  causal attribution was not established. No workaround or retry occurred.
- Second socket sample, config/mount/socket checks, local image query, all three
  fixture calls and per-container inspect/removal were **not reached**. No fixture
  output, target exit or duration is available. No container was created.
- Owned stop succeeded; explicit dedicated `colima list --json` reports Stopped.
  Raw evidence: `~/.capy/work/pybox-runtime-03-step2/`. Reports and the exact
  learning handoff are in Captain Drive under `reports/PYBO-5-step2.md` and
  `handoffs/PYBO-5/LEARNING.md`. Source/docs remain uncommitted in the sibling
  based at `262096c3e`; the parent checkout is preserved.

Step 1's manifest correlation timeout remains historical uncertainty, not a
follow-up gate. This pass made no registry/manifest/pull call. The pinned reference
is a multi-arch index by user designation; raw local `.Id` is not a config digest.
That pending decision was answered by the user's specific corrected-gate retry
approval above. The old raw attempt/evidence remains unchanged.

## M3a Step 3 — four finite real cases passed (2026-10-18)

- Controller-owned stable installation UUID, fresh run UUID and expiry labels
  precede create. The private installation file was initialized on first real use;
  unit metadata tests used temporary files. Existing unsafe metadata is not
  overwritten. Expiry alone does not reap a dead parent's objects.
- Ambiguous create recovery uses the exact run name and all three labels.
  Kill/removal additionally require a full ID and matching inspected identity;
  uncertainty stays `UNCONFIRMED`, with no prune or unknown-object deletion.
- The wall deadline is an absolute monotonic value anchored just before start.
  Create/start/inspect/query/kill/remove have distinct finite bounds, and cleanup
  shares one 15-second budget without resetting it after blocking operations.
- Wall-timeout handling uses an engine kill for a still-running matched object,
  not just cancellation of its CLI. Trusted target exit, OOMKilled, controller
  timeouts and original cleanup uncertainty remain separate facts.
- The latest ResourceWarning-elevated suite passed **81 tests in 10.751s**: 58 unchanged
  native tests, six updated container tests and 17 new focused tests. Docker was
  mocked; actual live evidence is separate below. A local read-only reviewer found
  a late-create race: an empty query cannot resolve an unacknowledged create.
  The fix retains `UNCONFIRMED`, with a regression for later daemon registration;
  the reviewer re-read it and found no remaining material issue. Before runtime,
  installed help confirmed attach forwards signals, so owned client cancellation
  changed from SIGTERM to SIGKILL; its strengthened regression/full suite and
  read-only re-review passed before the VM started.
- Production image/platform/private environment and defensive baseline are
  unchanged. No install, registry call, new commit or publishing occurred.

The one live pass ran 16:23:46.989327–16:24:10.144748 UTC, exit 0:

| Case | Actual observation |
|---|---|
| 8s sleep, 0.5s wall deadline | Client -9, still-running engine inspect, exact engine KILL, trusted target 137/OOMKilled false; about 0.560924s target lifetime, exact removal/absence. |
| Locally absent immutable digest, `--pull=never` | Real No such image, no target; original UNCONFIRMED plus separately retained empty identity/owner queries. |
| Failure after successful real create/before start | Same real ID recovered by all ownership labels, inspected created/nonrunning, removed without START. |
| Genuine dedicated Docker service/socket outage | Actual guarded EOF failures; original UNCONFIRMED/removed false/no exit; one verified restoration and separate empty query. |

One stopped foreign-labelled sentinel retained its same full ID after each
available-engine cleanup and restoration. Outage observation was unavailable.
Owner query was empty before deliberate exact test-ID/label sentinel teardown
and again before explicit VM stop/list Stopped. Raw evidence is
`~/.capy/work/pybox-runtime-03-step3/live/`; final details are in Captain
`reports/PYBO-5-step3.md`. No further runtime work follows this pass.

## Step 3 accepted; narrow classification refinement (2026-10-18)

- A fully captured/nontruncated positive-status response with no stdout, no timeout,
  and the canonical English daemon-rejection marker plus nonblank body establishes
  acknowledgement. This corrects the initial No-such-image-only draft; name-conflict
  and other completed non-cancellation rejections qualify too. A second successful
  complete/nontruncated empty name/all-label query
  is also required before `NOT_CREATED`. It means nothing was created, not that
  an object was removed: `removed` is false and target exit/ID/inspection are null;
  `runner_error` still records the failed create.
- No generic CLI status, arbitrary substring, empty daemon body, EOF, cancellation,
  timeout or partial capture becomes that acknowledgement. Daemon-prefixed
  context deadline exceeded/context canceled also remain UNCONFIRMED. The pinned
  English CLI adapter does not read a structured API response or promise transaction
  rollback. Failed/ambiguous queries and ID/name/label guards
  still fail closed. The late-create regression remains unchanged.
- All **86 ResourceWarning-elevated tests passed in 10.683s** (58 unchanged native,
  six container and 22 lifecycle/metadata/capture tests). Five new mocked methods
  cover the refinement and negative cases. Historical live missing-image
  UNCONFIRMED evidence was not rewritten or reclassified retroactively.
  Review's RPC `DeadlineExceeded` counterexample was reproduced and fixed by
  recognizing joined/separated deadline tokens; its negative regression passes.
- The learning chapter explicitly connects the observed client -9/engine still
  Running true to M1's Ctrl-C/closed-pipe lesson while distinguishing direct child
  cleanup from the separate Docker client/daemon/target process layout.
- No VM, container, service, registry or install action, and no Git write, was
  performed for this refinement. Proposed branch `checkpoint/m3a-step3` must be
  free and the cumulative diff shown before the one signed local commit. Step 4
  remains design-only after that checkpoint; no wrapper/watchdog/probe runs here.

## Deferred and security-gated

The main roadmap is the local library/CLI, later stdio MCP and a bounded agent
repair/evaluation loop. Live public execution/API/UI and deployment are dropped.
Step 3's four-case matrix is observed, not permission for further experiments;
the separate M3a-W watchdog, M3b restrictions, M3c kernel resource evidence,
MCP/AI and optional post-M6 Wasm remain outside this authorization. Native
execution is permanently unsafe/local-only, never an agent/MCP backend or
fallback. Later AI needs separate key/spending approval; no key is needed now.
