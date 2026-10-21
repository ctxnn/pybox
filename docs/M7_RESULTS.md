# M7 results — documentation, site, demo package and final review

20 October 2026. Executed by Opus 5.5 (`claude-opus-5-5`). The final
whole-repository review was done by a **separate Opus 5.5 session that did not
write the code or the docs** ([M7_FINAL_REVIEW.md](M7_FINAL_REVIEW.md)).
Nothing was committed, pushed or published. The dedicated VM was not started
and remained **Stopped** (read-only `colima list --json`, before and after).

## Delivered

| Artifact | State |
| --- | --- |
| [README.md](../README.md) | Rewritten: what PyBox is, prominent one-Mac/one-user caveat (hard-coded `HOME` and other paths; portability is future work), two execution paths, quickstart with and without the runtime, promises with evidence and limits, docs map. Pre-M7 README preserved at history/README-2026-10-19.md (local `legacy/docs/history/README-2026-10-19.md`). |
| REFERENCE.md (local `legacy/docs/REFERENCE.md`) | Library, CLI and exit codes, policy, deadlines, lifecycle, cleanup states, termination labels, inspection record, MCP, repair controller, native runner, troubleshooting, source map. Checked against source. |
| EXPLAINER.md (local `legacy/docs/EXPLAINER.md`) | Ten-chapter narrative built from LEARNING.md, plus "what happens when…" and proven/assumed/not-claimed. |
| M7_DEMO_RUNBOOK.md (local `legacy/docs/M7_DEMO_RUNBOOK.md`) | Segments labelled OFFLINE / REPLAY / LIVE, a 4-minute script, a storyboard mapped to site pages, a recording plan, launch copy and a publication checklist. |
| M7_PLAN.md (local `legacy/docs/plans/M7_PLAN.md`) | Audience, deliverables, claims map, sequence. |
| Docs site [`site/`](../site/index.html) | `index.html` (run inspector over six recorded runs), `how-it-works.html` (ten chapters, two interactive explanations), `reference.html`. Static HTML/CSS plus small inline scripts: no framework, no build, no execution backend. |
| Replay data [`docs-site/data/replay/`](../docs-site/data/replay/index.json) (moved from `site/data/` in M8 so CI can build the site) | 10 sanitized REPLAY files from `tools/export_replay.py` (read-only on `evidence/`); each names its source file and SHA-256. No home paths. |
| Design | Claude design canvas with three page artboards (sources and index (local `legacy/design-v1/README.md`)). An earlier Paper exploration (light "inspection tag" direction) was superseded at the owner's request and is not shipped. |
| [M7_FINAL_REVIEW.md](M7_FINAL_REVIEW.md) | Independent review: 0 Critical, 1 High, 2 Medium, 6 Low, 4 Info. |

## Review findings and resolution

| ID | Sev. | Resolution | Verification |
| --- | --- | --- | --- |
| F-01 | High | The automatic rule is unchanged: an unacknowledged CREATE still blocks admission, because an empty list cannot rule out a late create. Added an explicit operator path, `pybox cleanup --resolve-attempt RUN` / `cleanup_containers(resolve_attempts=…)`. It acts only after expiry + 60 s (`RESOLVE_MARGIN_S`), and only when a complete exact name + all-label query is empty. It clears the journal entry and reports `ABSENT_AFTER_EXPIRY`, never `NOT_CREATED`, and never kills or removes anything. Tokens are validated as 32-hex before any engine call. Docs corrected. | 3 new tests: too-soon refusal, implicit blocking, successful retirement with exact query and no rm/kill, CLI pass-through, malformed token |
| F-02 | Medium | A first `KeyboardInterrupt` during cleanup is recorded (`cancelled`, runner_error note) and cleanup is retried once, mirroring the native runner. A second interrupt propagates. That leaves at most two 15 s cleanup budgets; the MCP worker's 45 s deadline still bounds the total. Docs say so. | New test: interrupt during cleanup → retried, `cancelled: true` |
| F-03 | Medium | Sentinel warning added to README §2 and the REFERENCE CLI section, with a link to runbook D9. | Docs |
| F-04 | Low | The post-exit inspect now has its own 2 s inspect budget instead of the wall's remainder. | Full suite |
| F-05 | Low | README requires Python 3.11+ and explains the 3.9 failure. | Docs |
| F-06 | Low | Schema `code` gains a description stating the byte limit. REFERENCE explains chars vs bytes. | Full suite |
| F-07 | Low | The repair loop accepts `ABSENT` cleanup. | New test |
| F-08 | Low | Site pages, design index and this file now exist; runbook links retargeted. | Link targets present |
| F-09 | Low | `examples/mcp-client.json` uses a `/path/to/pybox` placeholder; the README caveat lists the other hard-coded files. Evidence-path relativization is left as a publication step (runbook checklist). | Docs |
| F-10 | Info | PROGRESS / ROADMAP updated to M7. | Docs |
| F-11 | Info | `ArgumentParser(prog="pybox")`. | Full suite |
| F-12 | Info | `cleanup_status` is `NOT_ATTEMPTED` when CREATE was never attempted. | New test |
| F-13 | Info | **Not changed.** Bounded waits only; disclosed. | — |

**Independently re-verified.** The same reviewer session re-checked every fix
(see "Re-verification" in M7_FINAL_REVIEW.md). F-01 to F-12 are resolved; F-01
"cannot remove or hide a real object"; F-02 is bounded. It found nothing new
above Low: R-1 (retry gets a fresh 15 s; REFERENCE now says so), plus R-2 to R-4
(Info: silent unknown `--resolve-attempt` token, calendar-clock margin,
interrupt after a successful cleanup). Those remain disclosed.

## Checks run

| Check | Result |
| --- | --- |
| Full suite, `/usr/local/bin/python` 3.11.3, `-W error::ResourceWarning` | **164 tests OK** (158 before + 6 new) |
| Native files `runner.py`, `_cpu_bootstrap.py`, `test_runner.py`, `test_cpu_limit.py` | Unchanged vs HEAD (`git diff --quiet`) |
| Offline quickstart (VM stopped) | Native hello exit 0; slow `--timeout 0.2` exit 124 / −15; missing opt-in exit 2; `container --inspect` exit 125 with cleanup `NOT_ATTEMPTED`; `cleanup` exit 125; MCP initialize → `2025-11-25`, tools `["run_python"]`, call → `isError`, `NOT_ATTEMPTED` |
| Site rendering | Served locally (`127.0.0.1:8765`) and checked in a browser at 1440×900 and 375×812. No page-level horizontal overflow on any page; the trace scrolls inside its own box on phones. Inspector tabs, `#scenario` deep links, and both explainer toggles work. No console errors. |
| Personal paths | No username or home path in `site/` or `docs/design/` |
| Replay fidelity | The reviewer regenerated all 10 payloads in memory: they match, and every source SHA-256 matches `evidence/raw` |

## What these checks are, and are not

- The 164 tests are unit, mock and local-protocol tests. The F-01/F-02/F-04 fixes
  are **unit-tested only**. No new live VM pass was run, so the dated runtime
  evidence (Step 4–M6) was recorded against the source before these fixes.
- Replay pages show recorded evidence from 18–19 October 2026, labelled as such.
- No provider request was made in M7.

## Not produced / outstanding

- **Recorded video:** not produced. It needs the owner's desktop and voice; the
  script, storyboard and recording plan are ready.
- **Publication:** not done and not authorized. The design canvas is private
  until shared from its Share menu. Hosting `site/` is a separate decision.
- **Commits:** Step 4 through M7 remain uncommitted for owner review
  ([CHECKPOINT_REVIEW.md](CHECKPOINT_REVIEW.md) proposes a split).
- **Portability:** the hard-coded single-account runtime is unchanged by design.

## Before the site and repository go public

The owner's note (`TODO.md`, 20 Oct) asked the right questions. Current state:

- **The site (`site/`) has no personal data.** Scanned for username, home
  paths, email, timezone, keys, sentinel IDs and installation-owner identity:
  none found. Replay files carry only run-scoped IDs and a temporary
  validation owner.
- **The repository does have personal data.** `pybox/container.py` (`HOME`,
  `USER`), `tools/runtime_validation.py`, `tools/validate_step4.py`,
  `tools/audit_secrets.py`, LEARNING.md, every results doc, the ledger, the
  handoff, the checkpoint review and the README snapshot contain
  `/Users/<name>/…` paths. Publishing the repository as-is publishes them.
- **Nobody else can use the restricted engine yet.** Today "download" means
  cloning the repository, which works only for the tests, the native runner
  and MCP discovery. The GitHub remote currently holds only the M1–M2 `main`
  branch. Making PyBox usable by others needs a portability milestone:
  a configurable runtime root, a consent-gated setup command that creates the
  Colima profile and caches the pinned image, discovery of the Docker context
  instead of a hard-coded hash, packaging (`pyproject.toml`, a `pybox` entry
  point), MCP client setup docs, and a fresh qualification pass on a second
  machine. Until then, the site truthfully presents PyBox as a research
  prototype with recorded evidence.
