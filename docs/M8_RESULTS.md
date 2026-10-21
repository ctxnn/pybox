# M8 results — installable and portable beyond one Mac

20 October 2026. Implemented by Opus 5.5 from the owner-approved
[M8 plan](M8_PLAN.md). Uncommitted for review. **Unit-tested only: no VM was
started, and nothing was set up on a second machine.**

## What changed

| Area | Change |
| --- | --- |
| Paths and identity (`pybox/container.py`) | `HOME = Path.home()`, user from `pwd`. The Docker context path is computed as `contexts/meta/sha256("colima-pybox")/meta.json`. `docker`/`colima` come only from `/opt/homebrew/bin` or `/usr/local/bin` (never `$PATH`), and the resolved binary must not be group- or world-writable. On this Mac every derived value equals the previous hard-coded one, checked directly. |
| Guard | Added a macOS-arm64 platform check, the tool checks, and plain-language errors: "restricted runtime is not set up (run: pybox setup)" and "dedicated VM is not running (start it with: pybox vm start)". Offline errors no longer echo home paths. Every earlier ownership, mode, content, context and socket check is unchanged. |
| `pybox setup [--yes]` (`pybox/runtime_setup.py`) | Dry run by default. With `--yes`: creates the private `0700` tree and `0600` files by exclusive creation (an existing file must match or setup stops), starts the dedicated profile with the qualified fixed flags, pulls only the pinned digest, verifies the profile config, guard and image, then stops the VM even on failure. An existing profile is never started, re-created or re-pulled. It never installs software. |
| `pybox vm start\|stop\|status` | Operates the `pybox` profile only. `start` verifies the profile readback (no mounts, no port forwarder, no VM address, not activated), the guard and the cached image, and stops again on any mismatch. It never pulls. |
| `pybox doctor` | Read-only JSON report; touches no containers and never starts the VM. |
| Packaging | `pyproject.toml`: stdlib only, Python ≥ 3.11, `pybox` console script, `_observe.sh` as package data. Build artifacts are ignored. |
| MCP | `examples/mcp-client.json` uses `"command": "pybox", "args": ["mcp"]`. |
| Personal paths | Code, tools, tests, examples and site contain no home path or username. The tools use `Path.home()`; the owner's qualification gates are unchanged. Historical docs were normalized to `~/…` or repo-relative text (114 occurrences in 13 files, path spellings only; numbers and outcomes unchanged). Links were rechecked. `evidence/` was not touched. |
| Docs and site | README (install → try → setup → run), REFERENCE (setup/vm/doctor, host-side rules, new troubleshooting), EXPLAINER, runbook checklist, the site's status banner, "Get it running" block and reference rows, and the design canvas. |

## Verification

| Check | Result |
| --- | --- |
| Full suite, Python 3.11.3, `-W error::ResourceWarning` | **176 tests OK** (164 + 12 new in `tests/test_runtime_setup.py`) |
| New tests cover | Derived paths; the context hash; the tool allowlist (writable, missing, outside the allowlist); platform refusal; guard messages; setup dry run changes nothing; `--yes` creates a private tree, then start → pull → stop; an existing profile is never started; a conflicting file is never overwritten; failed verification still stops the VM; `vm start` refuses to pull and stops on a missing image; doctor is read-only |
| Owner equivalence | Derived `HOME`, `PREFIX`, `CONTEXT`, `ENV["PATH"]` and the colima path match the pre-M8 constants on this Mac |
| Wheel | Built into scratch (`--no-build-isolation`, no network). It contains all modules, `_observe.sh` and the entry point. Installed into a throwaway venv: `pybox --help`, `pybox vm status` → `Stopped`, and `pybox mcp` from `/` returns `isError`, `NOT_ATTEMPTED` with the new message |
| On this Mac, read-only | `pybox doctor`: platform/tools/runtime ok, VM Stopped. `pybox setup`: everything `ok` and "profile already exists; will not start, change or re-pull it" |
| Site | Rendered at 1440×900 and 375×812: no overflow, no console errors |
| Native runner files | Unchanged vs HEAD |
| VM | Not started; `Stopped` throughout; sentinels not contacted |

## Not done / still to prove

- **Second-machine qualification.** Run `pybox setup --yes` on another Apple
  Silicon Mac, or a second macOS account. Then run the gated `tools/` checks and
  the quickstart. Until then, M8 is implemented and unit-tested, not qualified.
- `pybox vm start` does not repeat the qualification-only whole-Mac
  listener comparison. That stays in `tools/` and is stated in the docs.
- The validation drivers in `tools/` are still owner-specific: they reference
  the original checkout location and retained evidence.
- No PyPI release, no Linux or Intel support, no license chosen, nothing pushed.
  The GitHub remote holds only the M1–M2 `main` branch.
- M8 itself has not had an independent review; the M7 reviewer re-verified the
  M7 fixes only.
