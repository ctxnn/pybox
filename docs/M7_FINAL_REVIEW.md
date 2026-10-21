# M7 final whole-repository review

| | |
| --- | --- |
| Date | 2026-10-20 |
| Reviewer | Independent session; model **Opus 5.5** (`claude-opus-5-5`). It did not write the code or the docs under review. |
| Checkout | the repository root, branch `checkpoint/m3a-step3` (HEAD `1e07a74`) plus the uncommitted Step 4–M7 working tree, reviewed as found |
| Scope | `pybox/*` (all modules), `tests/*`, `tools/export_replay.py`, `tools/audit_secrets.py`, `site/data/replay/*.json`, `examples/*`, README, REFERENCE, EXPLAINER, M7_DEMO_RUNBOOK, M7_PLAN, ROADMAP, PROGRESS (header), STEP4/M3B/M3C/M4/M5/M6 results |
| Edited | This file only. No code, doc, evidence, runtime or Git state was changed. |

**What I ran:** the full unit suite (twice: Python 3.11.3, and the system Python 3.9.6 as a portability probe). The offline native-runner examples. Offline `pybox container` / `pybox cleanup`. An offline MCP session. `tools/audit_secrets.py`, with its report written to my scratch directory. A replay-fidelity check that imports `export_replay.py` and regenerates payloads in memory without writing anything. A relative-link checker. Three scratch mock simulations built on the repository's own test harnesses. `colima list --json` (read-only; it showed `pybox` **Stopped** before and after the review).

**What I did not run:** the VM, Docker, any `tools/validate_*.py`, `tools/evaluate_m6.py`, or any NVIDIA request. I did not run `tools/export_replay.py` itself, because it writes into `site/`. Nothing contacted the two retained sentinels: the Docker context and socket are absent while the VM is stopped, so the guard failed before any Docker call.

## Findings

| ID | Severity | Area | Location | Finding | Impact | Proposed fix |
| --- | --- | --- | --- | --- | --- | --- |
| F-01 | **High** | Reconciliation liveness + docs | `pybox/container.py:587-600` (entry created at `:417-418`, `:734`); `docs/REFERENCE.md:318`; `docs/EXPLAINER.md:280` | Take a journal entry with `container_id: null` that has no matching engine object. Reconciliation always records it as "unresolved create … a late object is possible". Nothing ever resolves it: neither expiry nor `pybox cleanup` changes the outcome. Several ordinary events produce such an entry: CREATE hitting its 5 s budget, a Ctrl‑C or MCP cancel during CREATE, or supervisor death after the journal write when the daemon never created the object. A scratch simulation with the repo's `test_step4` fake engine returned `complete: true, admission_allowed: false` at expiry, at +1 day and at +30 days. The only covered path (`test_ambiguous_attempt_is_retained_then_resolved_by_late_object`) assumes a late object eventually appears. | One ambiguous CREATE disables the restricted engine (CLI, MCP and repair) **permanently**. It fails closed, so it is not a safety issue. The documented remedy ("Run `pybox cleanup` after its 120 s expiry") does not work. The only real recovery is deleting the journal file by hand, which the same doc line discourages. | Add a bounded resolution rule. Example: when `now > expiry + margin`, with margin ≥ the maximum lifecycle, a complete exact name+label query that returns empty resolves the entry as `ABSENT_AFTER_EXPIRY` and the report says so. Alternatively, add an explicit operator command (`pybox cleanup --resolve-attempt <run>`) that re-queries before unlinking. Fix REFERENCE:318 and EXPLAINER:280 to match. Add a regression test with no late object. |
| F-02 | **Medium** | Interruption during cleanup | `pybox/container.py:725-743`, `:436`; `pybox/mcp.py:308-324` | `KeyboardInterrupt` is caught only in the `try` body. A SIGINT that arrives while `run_container` is in its `finally` (`_Control.cleanup` catches `Exception` only) aborts the KILL → rm → absence sequence and escapes `run_container`. The MCP worker keeps `active=True` until `run_container` returns, so a `notifications/cancelled` or client EOF sent after the target finished but before cleanup completed triggers this. In the CLI, a second Ctrl‑C does the same. A mock run (start interrupted, then a SIGINT during `kill`) ended with the exception escaping, the target still running, and the journal kept with its ID. The native runner already handles this case (`runner.py:204-267`), and EXPLAINER §1 tells this exact lesson. | No result: the CLI prints a traceback and no JSON, and MCP reports "Supervisor failed; cleanup is unconfirmed". The target runs until the guest timer and the object stays until the next run after expiry. Bounded and honest, but it contradicts REFERENCE:40-41 and 250-253 and EXPLAINER:277 ("cancel → same engine cleanup → `REMOVED`"). | Defer SIGINT once cleanup starts. In the worker, clear `active` (or only set a flag) before cleanup. In `run_container`, block SIGINT with `signal.pthread_sigmask` around the `finally`, or retry cleanup after `KeyboardInterrupt` as `runner.py` does. Add a test that interrupts during `kill`/`rm`. |
| F-03 | **Medium** | Docs vs retained evidence | `README.md:85-103` (also `docs/REFERENCE.md:69-77`, `:145-157`) | README §2 tells the reader to run `pybox container --inspect` and `pybox cleanup` with the VM running. It omits the warning in `M7_DEMO_RUNBOOK.md:102-107` (and STEP4/M3B results): these commands reconcile with the stable owner and **remove the retained, now-expired owned sentinel** `ba1b9ced…086c9`. | On the qualified Mac, following the README destroys deliberately retained evidence. | Copy the D9 warning into README §2 and the REFERENCE CLI/cleanup sections. Point readers to the temporary-owner arrangement in the validation tools when the sentinel must survive. |
| F-04 | Low | Deadline accounting | `pybox/container.py:713` | The post-exit inspect and policy re-check use `deadline=wall_deadline, limit="wall"`, so they are charged to the target's budget. If the target exits shortly before the deadline, the inspect can time out. A mock with 10 ms left produced `timeouts: ["wall"]`, a `RUNNER_ERROR`, CLI 125 and MCP `isError`, while `returncode: 0` was still reported from cleanup's inspect. | Conservative (it reports failure, not false success), but it misattributes an in-time exit as a deadline/runner error. `finite_check` then fails. Real-runtime frequency is unmeasured. | After attach returns, give the inspect its own `OPERATION_TIMEOUTS["inspect"]` budget. The wall bounds execution, not metadata. Or document the behavior in REFERENCE "Deadlines". |
| F-05 | Low | Setup requirement | `README.md:53-55`; `pybox/container.py:630-631` | README says "Python 3". `datetime.fromisoformat` cannot parse Docker's 9-digit fractional timestamps before 3.11, so every termination label silently degrades to `UNKNOWN`. Under `/usr/bin/python3` (3.9.6), 2 of 158 tests fail: `test_step4…classified` (`UNKNOWN != IN_CONTAINER_TIMER_CONSISTENT`) and `test_cpu_limit…exit_semantics` (`1 != 7`). | Running on the default macOS `python3` gives weaker records and a failing suite, with no warning. | State "Python 3.11+ (verified 3.11.3)". Optionally trim fractional seconds to 6 digits before parsing. |
| F-06 | Low | MCP schema | `pybox/mcp_policy.py:86` vs `:24` | `inputSchema.code.maxLength: 65536` counts characters (JSON Schema), but enforcement counts 65,536 UTF-8 **bytes**. | Schema-valid non-ASCII input can be rejected. A contract mismatch, not a safety issue. REFERENCE:227 already says bytes. | Say "65,536 UTF-8 bytes" in the tool/property description, or advertise `maxLength: 16384` and keep the byte check. |
| F-07 | Low | Repair controller | `pybox/repair.py:157` | Cleanup status `ABSENT` (known ID confirmed absent; `removed: true`) is treated as `CLEANUP_UNCONFIRMED` and halts the budget. | Needlessly stops a batch after a confirmed-clean outcome. | Add `'ABSENT'` to the accepted statuses. |
| F-08 | Low | Broken/pending links | `README.md:131`, `:139`; `docs/M7_DEMO_RUNBOOK.md:60-98`, `:147`, `:187` | `site/index.html`, `site/demo.html` and `docs/M7_RESULTS.md` do not exist yet; `site/` currently holds only `data/replay/`. All other relative links and LEARNING anchors resolve. | Dead links in the landing page and runbook. | Create the files (the concurrent site session) or remove the links, then re-run a link check. |
| F-09 | Low | Portability / publication hygiene | `examples/mcp-client.json:7`; `tools/runtime_validation.py:163`; `tools/audit_secrets.py:87-89`; results docs' absolute `evidence/raw` paths | The README caveat (lines 16-26) names only `HOME` in `container.py`. The example client config, a validation tool and the audit tool also hard-code the author's username and checkout path. Offline `runner_error` strings return absolute home paths to MCP clients (observed: `~/.pybox/runtime/docker/contexts/…/meta.json`). | It doesn't matter locally, but the strings would leak into any publication, and the example config fails on another account. | Extend the caveat to list these files. Use a `/path/to/pybox` placeholder in `mcp-client.json`. Before publishing, relativize evidence paths or keep them out of public pages. |
| F-10 | Info | Stale status | `PROGRESS.md:3` | The header says "Current continuation — M6" while M7 is in progress. | Minor confusion. | Update when M7 results land. |
| F-11 | Info | CLI cosmetics | `pybox/__main__.py:11` | Usage text shows `__main__.py` (observed: `usage: __main__.py [-h] …`). | Cosmetic. | `ArgumentParser(prog="pybox", …)`. |
| F-12 | Info | Status precision | `pybox/container.py:684-686`, `:762` | If `_save_attempt` fails before CREATE, `cleanup_status` stays the default `UNCONFIRMED`, although nothing was created and `NOT_ATTEMPTED` would apply. | Conservative mislabel. | Report `NOT_ATTEMPTED` when `create_attempted` is false. |
| F-13 | Info | Bounded waits | `pybox/container.py:233-236`; `pybox/mcp.py:18` | `_capture` kills the client's process group only while the leader is still alive, so descendants holding pipes are waited out to the deadline and not signalled. The worst-case lifecycle (15 + 5 + 2 + 1 + 2 + 2 + 15 + 2.1 s, plus up to 1 s kill-wait per operation) can approach the 45 s MCP worker deadline. | Both are bounded. In the pathological case the worker is SIGKILLed and the result honestly says `UNCONFIRMED`. | Optionally `killpg` the group whenever the loop exits on deadline, and widen the worker deadline margin. |

**Areas with nothing material found:**
- **Caller-influenced policy.** The only caller input is `timeout_s`. It is validated (`0 < t ≤ 2`, finite, not bool), and the readback check covers it through `Cmd`.
- **Policy readback completeness.** No gaps found for the fixed create argv.
- **Admission lock and journal file safety.** `O_NOFOLLOW`, fstat ownership/mode/nlink checks, and atomic replace.
- **Identity matching before destructive operations.**
- **Observer framing and parser strictness.**
- **MCP framing, bounds, ID reuse and stdout separation.**
- **Credentials.** The key travels only over the worker's stdin. Envs are replaced with the fixed `ENV`. Stderr is redacted. The response is checked for the key. No key reaches Docker or the MCP worker.
- **Replay fidelity.**

## Verification results

| Check | Command / method | Result |
| --- | --- | --- |
| Unit suite (3.11.3) | `/usr/local/bin/python -B -W error::ResourceWarning -m unittest discover -s tests -v` | **Ran 158 tests in 12.598s — OK** (exit 0) |
| Unit suite (3.9.6, probe) | same with `/usr/bin/python3` | 158 run, **2 failures** (see F-05) |
| Native hello | `python -B -m pybox run examples/hello.py --unsafe-local` | exit **0**; `returncode 0`, separate stdout/stderr, `group_cleanup_confirmed true` |
| Native deadline | `… run examples/slow.py --unsafe-local --timeout 0.2` | exit **124**; `timed_out true`, `returncode -15`, `SIGTERM` |
| Native opt-in refusal | `… run examples/hello.py` | exit **2** before launch |
| Native CPU soft limit | `… run examples/compute.py --unsafe-local --timeout 10 --cpu-soft-limit 1` | `returncode -24` (`SIGXCPU`), `cpu_limit_installed true` |
| Offline container | `printf 'print(1)\n' \| python -B -m pybox container --inspect` | exit **125**. Cleanup `NOT_ATTEMPTED`; explanations `RUNNER_ERROR`, `COUNTERS_UNAVAILABLE`, `POLICY_NOT_VERIFIED_BEFORE_START`. The guard failed on the absent context `meta.json` before any Docker call. |
| Offline cleanup | `python -B -m pybox cleanup` | exit **125**, `complete false`, `admission_allowed false`; the attempt journal stayed empty |
| Offline MCP | scripted session over `python -B -m pybox mcp`, stdin held open until each reply | `initialize` → `2025-11-25`, server `pybox 0.1.0`. Pre-init `tools/list` → `-32002`. `tools/list` → `["run_python"]`. Over-cap `max_output_bytes` → `isError` with a validation message. `tools/call` → `isError: true`, cleanup `NOT_ATTEMPTED`, 0.04 s. Server exit **0** after EOF; empty stderr. |
| Secret audit | `python -I -B tools/audit_secrets.py --output <scratch>` | `project_artifacts_clean: true`, positive controls true. 7,339 files / 53.7 MB plus 157 Git objects; 0 findings, 0 errors. |
| Replay fidelity | regenerated all 10 payloads in memory via `export_replay` functions | All 10 match the files on disk. Every `sources[].sha256` matches `evidence/raw`. All carry `label: "REPLAY"`, and `index.json` has 10 entries. No `/Users/`, username, installation-owner UUID, `nvapi-` or tmp paths. The only 32-hex value is a validation-time temporary reconciliation owner. |
| Replay facts | read from the replay payloads | m4-timeout: 137, `SUPERVISOR_KILL_OBSERVED`, 0.447187 s. m4-memory: exit 0, `OOMKilled` true, `OOM_KILL_COUNTER_OBSERVED`, stdout `-9`. m4-pids: stdout `30 6`. step4: supervisor −9, PID 1 `timeout` UID 10000, 137 after 3.028 s, 0/0 engine KILL commands. m5: 0 messages with id 999. m6: `restart` answer rejected, then `49995000`. |
| Links | relative-link/anchor checker over README, PROGRESS and docs/*.md | Only the F-08 targets are missing (and this file, now present) |
| Scratch simulations (mocked, not runtime evidence) | repo fake engines under `unittest.mock` | Confirmed F-01, F-02 and F-04 as described |

## Claims spot-check

| Claim (doc) | Source / evidence | Verdict |
| --- | --- | --- |
| Fixed policy: UID 10000, cap-drop ALL, NNP, no network, RO root, 16 MiB noexec `/tmp`, 128 MiB = mem+swap, 32 tasks, 0.5 CPU, nofile 128, log none (README:116, REFERENCE:88-96) | `_create_args` `container.py:159-166`; `_check_policy` `:315-332` | ✔ |
| PID 1 = `timeout -s KILL <timeout_s+1>` (README:117, EXPLAINER:127) | `_timer_args` `:155-156`, `TIMER_MARGIN_S=1.0` | ✔ |
| Budgets: create 5, start 2, inspect/query/kill 2, remove 3, cleanup 15, expiry 120 (REFERENCE:107-109) | `OPERATION_TIMEOUTS`, `CLEANUP_BUDGET_S`, `EXPIRY_S` `:42-44` | ✔ |
| Collector arms in 1 s, guest 6 s, Mac 8 s (REFERENCE:110) | `container.py:272`, `:279`, `:300` | ✔ |
| CLI exit order 130 → 125 → 124 → 0/1 (REFERENCE:75) | `__main__.py:58-64` | ✔ (observed 125 offline) |
| `cleanup` exits 0 only if complete and error-free (REFERENCE:76) | `__main__.py:37` | ✔ (observed 125) |
| MCP bounds 32 calls / 256 msgs / 512 KiB frame / 32 depth / 64 KiB record / 256 KiB response / 1 MiB queue / 5 s stall / 45 s / 22 s (REFERENCE:241-248) | `mcp_policy.py:7-13`, `mcp.py:17-20`, `:40`, `:92` | ✔ |
| `max_output_bytes` 1–8,192, default 4,096; `timeout_s` ≤ 2 (REFERENCE:225-229) | `mcp_policy.py:27-33` | ✔ (schema byte/char nuance: F-06) |
| Repair limits 16/24/2/900 s, 50 s reserve, 2 KiB diagnosis, 8 KiB code (REFERENCE:270-276) | `repair.py:15`, `:24-33`, `:59`, `:104-105` | ✔ |
| NIM model / thinking off / no retries / key only in memory + worker stdin (REFERENCE:265-268) | `nim.py:13`, `:31-32`, `:74`; `_nim_worker.py:29` | ✔ |
| Native runner: TERM → KILL at 0.15 s, 0.6 s budget, timeout ≤ 60, output ≤ 1 MiB (REFERENCE:294-298) | `runner.py:13-16` | ✔ |
| 13 M3b checks; SIGTERM/SIGSTOP on PID 1 ≈ 3.026/3.027 s (README:116-117, EXPLAINER:174-176) | M3B_RESULTS (3.025546 s, 3.026608 s) | ✔ |
| Supervisor SIGKILL → 3.028 s (README:117, EXPLAINER:155) | STEP4_RESULTS (3.028433 s); replay timestamps | ✔ |
| 9 M3c checks; 30 children + 6 refused; OOM with exit 0 (EXPLAINER:187-191) | M3C_RESULTS:66-68 | ✔ |
| UNKNOWN label from ~13 ms clock ordering (EXPLAINER:219-222) | M4_RESULTS:93-96 ("about 12–14ms") | ✔ |
| 0.4 s request → 0.447 s, `SUPERVISOR_KILL_OBSERVED` (RUNBOOK D4) | M4_RESULTS:73; replay | ✔ |
| 13 live MCP checks; ID-999 spoof (README:120, EXPLAINER:230-231) | M5_RESULTS:3, :97; replay | ✔ |
| 8 sessions, 4/4 per group; 5 vs 4 requests; 1,850 vs 10,973 prompt tokens; `restart` / 256 MB (README:121, EXPLAINER:255-265) | M6_RESULTS:3-4, :110-114, :128-129 | ✔ |
| 158 tests (README:63, RUNBOOK:38) | this run | ✔ (on 3.11; see F-05) |
| "Run `pybox cleanup` after its 120 s expiry" resolves an unresolved create (REFERENCE:318); "until reconciliation resolves it" (EXPLAINER:280) | `container.py:587-600` | ✘ **Overclaim** (F-01) |
| Ctrl‑C / MCP cancel → same engine cleanup → `REMOVED` (REFERENCE:40-41, 250-253; EXPLAINER:277) | `container.py:725-743`, `mcp.py:308-324` | ◐ True for an interrupt during execution; false for one during cleanup (F-02) |
| "Python 3" requirement (README:53) | F-05 | ◐ Needs 3.11+ |
| Runtime is single-user/single-Mac (README:16-26; EXPLAINER:294-295; M7_PLAN:46) | `container.py:28-40`; also F-09 files | ✔ Stated clearly. The list of hard-coded files is incomplete (F-09). |

## Remaining limitations (not defects; correctly disclosed in the docs)

- Finite, control-specific restriction and resource checks. No claim about arbitrary hostile code. NNP setuid-exec transitions were not measured.
- No hard real-time bounds: a healthy, scheduled VM, an intact timer and the pinned English Docker CLI error format are assumed.
- Mac UTC and guest Docker UTC are unaligned. `SUPERVISOR_KILL_OBSERVED` compares them, so a real KILL can be labelled `UNKNOWN` (observed in M4 attempt 01).
- Counters are live samples. Finals and lifetime deltas are unknown.
- No watchdog: stopped objects remain until another PyBox invocation after expiry.
- MCP was exercised only with an independent local client. There is no SDK or GUI interoperability claim.
- M6 covers 4 synthetic problems, is not a benchmark, and its provider cost is `null`.
- The runtime is hard-coded to one macOS account. Portability is future work.

## Kinds of evidence (kept distinct)

- **Mocked or unit tests** (the 158-test suite and my three scratch simulations) show code paths and branch logic against fake engines, observers and providers. They are **not** runtime evidence and do not show kernel, Docker or VM behavior.
- **Real recorded kernel/runtime evidence** is the dated Step 4 and M3b–M5 qualification passes under `evidence/raw` (git-ignored), summarized in the results docs. I re-checked the cited numbers and the replay hashes against those files. I ran **no** new live container or VM pass.
- **Provider experiments** are the M6 NVIDIA NIM sessions (`nvidia/nemotron-3.5-lightning-30b-a3b`): real requests recorded on 2026-10-19 and read from evidence. I made no provider request.
- **Documentation review** is this report's comparison of docs against source constants and recorded results. The offline command results above are fresh observations made today on this Mac with the VM Stopped.

## Summary

- **High:** F-01 (an unresolved-create journal entry blocks admission permanently; the documented remedy is wrong).
- **Medium:** F-02 (an interrupt during cleanup aborts it), F-03 (the README live quickstart would remove the retained owned sentinel without warning).
- **Low and Info:** F-04 to F-13. No Critical findings.
- **Verified:** 158/158 tests pass on Python 3.11.3. The offline CLI, native and MCP behavior and every audited number match the code and recorded evidence, except where the findings above say otherwise.

## Re-verification (2026-10-20, same reviewer, Opus 5.5 `claude-opus-5-5`)

I re-checked the fixes made by the implementing session, under the same rules as before: no VM, Docker, provider calls or Git operations, and this file is the only one edited. `colima list --json` showed `pybox` **Stopped** before and after, and the runtime attempt journal was empty.

### Status of each finding

| ID | Status | What I checked |
| --- | --- | --- |
| F-01 | **Resolved (operator path; automatic rule unchanged by design)** | See the F-01 safety analysis below. `container.py:603-618` (resolve branch); `cleanup_containers` `:631-643`. REFERENCE (cleanup section, troubleshooting) and EXPLAINER:280 now describe the real behavior. |
| F-02 | **Resolved, bounded** | See the F-02 bounds analysis below. `container.py` `finally` of `run_container`. REFERENCE:40-42 and :269-270 and EXPLAINER:277 match. |
| F-03 | Resolved | README §2 `[!WARNING]` names `ba1b9ced…086c9` and links to runbook D9; that anchor resolves. REFERENCE:88 carries the same warning. |
| F-04 | Resolved | The post-exit `inspect_owned()` no longer receives `wall_deadline`, so it uses its own 2 s inspect budget. The REFERENCE budgets row says so. |
| F-05 | Resolved | README:57 says "Python 3.11 or newer". |
| F-06 | Resolved | `mcp_policy.py:87`: the `code` description states 65,536 UTF-8 bytes; the schema `maxLength` is unchanged and the byte check is still enforced. |
| F-07 | Resolved | `repair.py:157` accepts `ABSENT`; new test `test_confirmed_absent_cleanup_does_not_halt_the_batch`. |
| F-08 | Resolved | `site/index.html`, `how-it-works.html`, `reference.html`, `docs/design/README.md` and `docs/M7_RESULTS.md` exist. All Markdown relative links and anchors in README, PROGRESS, docs/*.md and docs/design/*.md resolve. Every `href`/`src` in the three site pages and design/README.md resolves (50 + 8 refs). The runbook's `#normal/#deadline/#oom/#killed` anchors are handled by script (`index.html:302`); `#c9` and `#c10` are real IDs. The site embeds its data inline (no `fetch`), so `file://` works. Spot-checked figures (0.447, 3.028, `30 6`, 49995000, id 999, 164 tests) appear with REPLAY/recorded labels. The site HTML contains no `/Users/`, username or `nvapi-`. |
| F-09 | Resolved | `examples/mcp-client.json` uses `/path/to/pybox`. The README caveat lists `mcp-client.json`, `tools/runtime_validation.py`, `tools/audit_secrets.py` and the home paths echoed in errors. Results docs still contain absolute evidence paths; that is a publication-checklist item. |
| F-10 | Resolved | The PROGRESS header now reads "Current continuation — M7, 20 October 2026". |
| F-11 | Resolved | Observed `usage: pybox [-h] {mcp,container,cleanup,run} ...`. |
| F-12 | Resolved | `cleanup_status` is `NOT_ATTEMPTED` unless `create_attempted`; new test `test_journal_failure_before_create_reports_not_attempted`. |
| F-13 | Not fixed; disclosed | Unchanged. Still Info. |

### F-01 safety analysis

The resolve branch handles only journal entries that have no ID **and** whose token the owner-label listing earlier in the same admission did not show. It never calls `rm` or `kill`; its only side effect is `_clear_attempt`. Its preconditions, in order:
1. The token is valid 32-hex (checked before admission or any engine call).
2. `now ≥ expiry + 60 s`.
3. A complete exact `name=^/<name>$` + all-label query is empty. An incomplete query raises through `metadata`.

Mock probes using the repo's `test_step4` fake engine:

| Case | Outcome |
| --- | --- |
| Before the margin | Kept, error reported, admission blocked |
| After the margin, empty engine | Entry cleared, `ABSENT_AFTER_EXPIRY`, admission allowed |
| A late **running** object present | Not resolved, object untouched, admission blocked |
| A late stopped expired object present | Handled by the normal path (exact removal) |
| Incomplete identity query | `complete: false`, entry kept |
| Token not in the journal | No effect |

A wrongly cleared entry cannot hide a real object, because any late object still carries the owner label and is listed and reconciled on every later run. **It cannot remove or hide a real object.**

### F-02 bounds analysis

Only `control.cleanup()` is wrapped. A first `KeyboardInterrupt` sets `cancelled` and adds a `runner_error` note, then cleanup is retried once; an interrupt during the retry propagates. Probes:

| Probe | Outcome |
| --- | --- |
| One interrupt during `kill` | Returned `REMOVED`, `cancelled: true` |
| Interrupts during both attempts | Propagated, as documented; the journal keeps the ID for next-run reconciliation |

Each attempt has its own 15 s budget. Worst case is about 30 s of cleanup plus the per-operation kill-wait (R-1).

### Verification results

| Check | Result |
| --- | --- |
| Unit suite, `/usr/local/bin/python` 3.11.3, `-B -W error::ResourceWarning -m unittest discover -s tests` | **Ran 164 tests in 12.742s — OK** |
| Offline `pybox container` / `pybox cleanup` | exit **125** / **125** |
| `pybox cleanup --resolve-attempt XYZ` | exit **125**, `runner_error: "resolve_attempts must be 32-hex run tokens"`, no engine call |
| `pybox cleanup --resolve-attempt <32×a>` (offline) | exit **125**: the guard fails before Docker |
| Native runner files | `pybox/runner.py`, `pybox/_cpu_bootstrap.py`: no diff against HEAD |

### Remaining or new issues

| ID | Severity | Location | Issue | Proposed fix |
| --- | --- | --- | --- | --- |
| R-1 | Low | `docs/REFERENCE.md:116`; `container.py` `_Control.cleanup` (per-call `deadline`) and the retry in `run_container` | REFERENCE says cleanup is "15 s shared … not restarted per operation", but an interrupted cleanup's retry gets a **fresh** 15 s, so the worst case is about 2 × 15 s. In MCP, the 22 s grace from the cancel still covers retry + collector (about 17 s). The absolute 45 s worker deadline can still SIGKILL a late retry, which then reports `UNCONFIRMED` (honest). | Note the retry budget in REFERENCE, or pass one shared deadline to both attempts. |
| R-2 | Info | `container.py:603` | `--resolve-attempt` with a token that is not in the journal is silently ignored, so cleanup can exit 0 with no feedback on an operator typo. The real blocking entry still reports its error, so this is harmless. | List unmatched tokens in `runner_error` or a field. |
| R-3 | Info | `container.py:606` | The resolution margin uses calendar time, so a forward clock jump could retire an entry early. Safety is unaffected (see the F-01 analysis); only admission resumes sooner. | Accept, or also require journal-file age (mtime) past the margin. |
| R-4 | Info | `run_container` `finally` | An interrupt during the journal update or `observer.finish()` (after cleanup succeeded) still escapes without a result. Cleanup is already done, and the journal self-heals on the next run (known ID → `ABSENT`). | Optional: extend the deferral to the whole `finally`. |

**Re-verification verdict:** all High and Medium findings (F-01, F-02, F-03) are resolved, along with F-04 to F-12. No new issue is above Low. F-13 and R-1 to R-4 remain as disclosed Low/Info items. These verdicts rest on code reading, mocked probes and offline commands; no new live runtime evidence was produced.
