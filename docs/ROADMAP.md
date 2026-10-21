# PyBox roadmap and release gates — revised 19 October 2026

The owner selected the in-container timer plus next-run reconciliation contract.
The earlier requirement for zero owned objects without another invocation is
dropped. There is no watchdog process, daemon, or background reaper.

## Accepted contract

1. **Execution deadline:** untrusted code must stop running by its in-container
   deadline even if the Mac supervisor dies. The Mac's requested wall deadline
   remains the primary path. PID 1 is `timeout -s KILL <wall_timeout + 1s> python
   -I -B -u -`; the extra second is an explicit fallback margin. Thus a two-second
   requested host deadline has a three-second guest fallback, measured from
   wrapper execution, not API entry or CREATE. Healthy scheduled VM/kernel and
   an intact timer are assumptions; these are not exact real-time bounds.
2. **Object reclamation:** stopped leftovers are removed by the next container
   run's reconciliation or manual `python -B -m pybox cleanup`, once their expiry
   has passed. Before expiry they are reported and kept. Without another command
   objects may remain indefinitely; bounded execution does not imply deletion.

The deadline is a release requirement for untrusted execution, not a claim that
finite tests prove resistance to arbitrary target interference. M3b's specific
PID 1 SIGTERM/SIGSTOP cases now pass; their evidence and limits are recorded in
[M3B_RESULTS.md](M3B_RESULTS.md).

## Step 4 implementation and release gates

- Fixed timer PID 1, private PID namespace, no init shim or restart, same pinned
  local image and defensive policy. Keep Mac operation/wall/cleanup deadlines.
- Verify real PID 1 and engine timestamps. Distinguish an acknowledged PyBox KILL
  from timing consistent with the timer. Exit 137 alone proves neither. Timing
  plus no KILL cannot exclude target self-termination; unknown stays unknown.
- Reconcile before every **container** run and expose manual cleanup. Report all
  installation-owned objects, expiry/state, removed IDs, unresolved attempts and
  errors. Only expired, stopped full IDs with exact name/owner/run/expiry readback
  may be removed. Never kill during reconciliation, force-remove, prune, or touch
  a foreign or unexpired object. Failure/ambiguity blocks new execution.
- Hold a nonblocking single-flight OS lock across reconciliation and execution.
  Persist private identity before CREATE, then the acknowledged full ID. Abrupt
  supervisor death releases the lock. An unknown CREATE plus an empty query stays
  reported and blocks admission; it is not a no-create acknowledgement.
- Production expiry remains 120 seconds after identity allocation, covering the
  bounded setup, execution/fallback and cleanup allowances. Do not change the Mac
  clock or shorten production expiry for a live test. Recheck expiry before RM.
- Real disposable-supervisor SIGKILL after target execution begins: prove signal
  9, actual PID 1, terminal state near the guest timer, no rescue KILL, and the
  stopped object still present. After actual expiry, show next-run/manual cleanup.
- Real death after CREATE/before START, including lost acknowledgement: no target
  start is invented, object remains visible, later exact reconciliation removes
  it. Foreign and unexpired sentinels survive all reconciliation operations.
- Save finite fixture command histories, raw observations, source hashes and
  failures. Stop the dedicated VM and stop for owner review. No Step 4 commit
  until reviewed; no push is authorized.

## Remaining milestones

| Milestone | Required evidence before release |
| --- | --- |
| M3b restrictions — finite matrix passed | 13 bounded checks passed, including target SIGTERM/SIGSTOP to PID 1 (~3.026s/~3.027s), filesystem/scratch, private TCP/synthetic DNS, identity/capability/kernel NNP/seccomp, descriptors and output/log storage. See [actual results and limits](M3B_RESULTS.md). NNP setuid-file exec transitions and universal hostile-code safety were not measured. |
| M3c resources — finite qualification passed | Nine checks / thirteen final-run fixtures passed with independent live memory/OOM, PID/task and CPU counters; Linux RLIMIT_CPU comparison completed. Missing final reads remain explicit. See [actual evidence](M3C_RESULTS.md). CPU bandwidth is not an exact cumulative CPU budget. |
| M4 inspection — qualified locally | Production collector arms before START without target cooperation or changing timer PID 1. Versioned inspection/CLI separates policy, readback, live/unknown evidence, clock domains, capture and cleanup. Eight real cases passed three times; 122 tests passed. See [results and limits](M4_RESULTS.md). Exact finals and clock alignment remain unknown. |
| M5 local stdio MCP — qualified locally | Pinned 2025-11-25 stdio profile exposes only `run_python` through the restricted engine. Thirteen live checks and 139 tests passed; cancellation/disconnect cleanup, bounded delivery and protocol/data separation observed. See [results and client limits](M5_RESULTS.md). No SDK/GUI interoperability claim. |
| M6 repair/evaluation — finite comparison completed | Full-source controller, fixed container execution, durable reservations, request/step/token/byte/time/concurrency limits and strict action validation. Owner-authorized free NIM replacement model repaired 4/4 cases in each group; 158 tests pass. Two failed GLM reservations remain unknown. See [results, costs and limits](M6_RESULTS.md). |
| M7 documentation design, explainer and demo — delivered for review | README/reference/explainer/runbook and a static docs site with a run inspector over recorded evidence. Designs are in a Claude design canvas (the owner replaced Paper mid-milestone). An independent Opus 5.5 review found 0 Critical / 1 High / 2 Medium; fixes are unit-tested (164 tests) and re-verified (no new issue above Low). No screen recording was made; the site's walkthrough is an animation rendered from recorded evidence. See [M7 results](M7_RESULTS.md) and the [final review](M7_FINAL_REVIEW.md). |
| M8 installable and portable (Apple Silicon) — implemented, unit-tested | Derived paths, allowlisted tools, consent-gated `pybox setup`, `vm`, `doctor`, `pyproject.toml`, and personal paths removed. 176 tests pass. Second-machine qualification is pending. See [plan](M8_PLAN.md) and [results](M8_RESULTS.md). A fresh from-nothing setup ran in a throwaway installation on the build Mac during M9 (3 min 17 s). |
| M9 useful for real work — implemented, live-checked in a throwaway installation | `data` image (hash-locked numpy/pandas, 512 MiB/64 tasks/1 CPU, verified by image ID and recipe hash), deadlines up to 30 s, files in/out (64 files, 8 MiB each way, untrusted outputs), `pybox exec` with a readable receipt, configurable MCP (`--max-timeout`, `--images`, `files`, `return_files`), PyPI-ready packaging (Apache-2.0), benchmarks (0.316 s median per run). 18 live checks including a Claude Code session; 198 tests. Not published; second Mac pending. See [plan](M9_PLAN.md) and [results](M9_RESULTS.md). |
| M10 ready to share — implemented, reviewed, live-checked | matplotlib in `data`; your own images from hash-locked lock files; final readings for opt-in runs; allowlisted direct-ssh watcher (0.204 s median per run); Cursor tested; independent security review (2 Medium, 6 Low, 6 Info, 11 doc overclaims) all resolved; 209 tests. Claude Desktop untested; not pushed or published. See [results](M10_RESULTS.md) and [review](M10_SECURITY_REVIEW.md). |

### M7 documentation and sharing deliverables

- **Documentation:** a polished, accessible quickstart, setup and usage guides,
  architecture/trust-boundary explanations, API/MCP reference, troubleshooting,
  reproducible experiments and clearly stated guarantees and limitations. Design
  the visual system, page layouts, diagrams and presentation assets in **Paper,
  the design app**; retain editable designs and export usable assets for the docs.
- **Explainer and demo:** turn LEARNING into a coherent narrative grounded in the
  actual implementation and evidence. Plan the audience, message, video format
  and duration, script/storyboard, and safe demonstration cases. Distinguish
  recorded/replayed examples from live execution; exclude secrets and personal
  desktop content.
- **Sharing package:** prepare the repository presentation, video assets and
  accompanying launch copy; choose the intended channels (for example GitHub,
  YouTube or LinkedIn) and a publication checklist. Preparation does not authorize
  publishing or change the optional showcase website's scope.

M7's finish line is a cohesive, technically accurate, visually excellent and
review-ready documentation/demo package, with working examples and traceable
evidence. Paper here means the design application, not an academic paper.

### Final completion gate — Opus 5.5 and whole-repository review

Use **Opus 5.5** to execute M7 and perform the final whole-repository review.
Review the implementation and architecture, tests, CLI/MCP behavior, lifecycle
and resource/security controls, dependencies, setup instructions, examples,
documentation and demo assets. Check that public-facing claims match the actual
implementation and recorded evidence.

Run the full applicable test/check suite, verify reproducible examples, resolve
material findings, and rerun affected checks. Deliver a final review report with
findings, fixes, verification results and remaining limitations before the final
handoff. Existing owner-review requirements for commits and publication remain.

M1/M2 and M3a Steps 1–3 are completed historical checkpoints. The definite-create-
rejection refinement is already in signed local Step 3 commit `1e07a74` on
`checkpoint/m3a-step3`. Public execution/API/UI/deployment and persistent sessions
remain outside the main roadmap. Optional Wasm follows M6 as a separate decision.

This file supersedes the pre-selection Step 4 alternatives and watchdog release
gate in earlier handoff/roadmap snapshots; those remain historical evidence.

Current continuation (20 October 2026): M8 portability is implemented and
unit-tested; a second-machine qualification pass is the next gate. Before that, M7 documentation, site, demo package and
final review are delivered for owner review ([M7_RESULTS.md](M7_RESULTS.md)).
Review fixes changed reconciliation only by adding an explicit, operator-invoked
`--resolve-attempt` path. The automatic "unacknowledged CREATE blocks admission"
gate above is unchanged. Step 4–M8 changes remain uncommitted; both sentinels are
retained and the VM is Stopped. No push or publication is authorized.
