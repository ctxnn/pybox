# M9 results — useful for real work

Date: 21 October 2026. Plan: [M9_PLAN.md](M9_PLAN.md), approved by the owner the same
day, together with the choices "throwaway install" for live tests, `pybox exec` as the
command name, and Apache-2.0. Nothing was committed, pushed or published.

## What was built

| Item | Where | State |
| --- | --- | --- |
| Box profiles; `data` image with hash-locked numpy 2.5.4, pandas 3.0.6, python-dateutil, six, tzdata | `pybox/boxes.py`, `pybox/images/data.lock`, `runtime_setup.build_image` | Live-checked |
| Local image record (`images.json`, private), verified per run by image ID and recipe SHA-256 | `container.local_images`, `resolve_box` | Live-checked |
| Per-box policy check (image, memory, swap, PIDs, CPU, tmpfs, PID 1 command) | `container._check_policy` | Unit-tested; live runs passed it |
| Deadlines up to 30 s; start budget follows the deadline; watcher scales (20 samples at 0.05 s, then spread) | `boxes.MAX_TIMEOUT_S`, `container._Observer`, `_observe.sh` | Live-checked |
| Files in and out over the attach streams via a fixed bootstrap; host-side strict parsing and safe writes | `boxes.BOOTSTRAP`, `boxes.split_outputs`, `pybox/transfer.py` | Live-checked |
| `pybox exec` with a readable receipt; `--json`, `-q` | `pybox/__main__.py`, `pybox/receipt.py` | Live-checked |
| `pybox setup --with data`, timed summary and next steps; readable `doctor` | `pybox/runtime_setup.py` | Live-checked |
| MCP: `image`, `files`, `return_files`; server `--max-timeout`, `--images`; encoded-size bounds for returned files | `pybox/mcp.py`, `pybox/mcp_policy.py` | Live-checked, incl. Claude Code |
| Packaging: version 0.3.0, Apache-2.0 `LICENSE`, PyPI metadata, `pybox.images` package data, `--version` | `pyproject.toml` | sdist + wheel built, `twine check` passed, installed and run in a clean venv |
| Workflows: release (PyPI trusted publishing), tests (macOS, 3.11–3.13) | `.github/workflows/release.yml`, `tests.yml` | Written; **not run** (nothing pushed) |
| Homebrew formula template | `packaging/homebrew/pybox.rb` | Template; needs a PyPI release for `url`/`sha256` |
| Benchmark | `tools/bench.py` | Run live |
| Docs | 3 new site pages (files, packages, performance), 12 updated, README, this file | Built; links and anchors check clean |

The default run is unchanged: same image, limits, PID 1 command (`python -I -B -u -`),
tmpfs and policy check, so the M3–M5 evidence still describes it. A unit test pins the
default `docker create` arguments byte for byte.

## Live evidence

Recorded in a **throwaway installation** (`HOME=~/.pybox-qa`) on the build machine, so
the real installation and its retained sentinel containers were never touched. The
throwaway setup ran from nothing with the current code: **3 min 17 s** (VM download,
pinned image pull, verification, VM stop). `pybox vm start` took 21 s; building the
`data` image took 26 s.

| # | Check | Result |
| --- | --- | --- |
| 1 | `echo 'print(6*7)' \| pybox exec -` | `42`; exit 0 in 0.166 s; settings verified; removed |
| 2 | `--json` record | image `stdlib`, 134217728 bytes, policy verified, `REMOVED`, `files: null`, counters collected |
| 3 | Files in/out, stdlib | CSV in; 2 files back; symlink to `/etc/passwd` skipped; write to input copy → `PermissionError` |
| 4 | pandas in `data` with files | Correct groupby, result CSV back; peak 42.4 MiB of 512 (after the watcher fix below) |
| 5 | `sleep(12)`, `--timeout 15` | Exit 0 after 12.13 s; 50 samples |
| 6 | `sleep(60)`, `--timeout 30` | Exit 137 at 30.01 s, `SUPERVISOR_KILL_OBSERVED`; removed |
| 7 | 300 MiB numpy array in `data` | Exit 0 |
| 8 | 700 MiB array in `data` | Exit 137; engine `OOMKilled`; cause "not established"; peak seen 428.8 MiB |
| 9 | Network from `data` | DNS failure: no network |
| 10 | `--timeout 31` | Refused before any box (exit 2) |
| 11 | 9 MiB output + 70 small files | 64 files back; big file and 6 others listed as not brought back |
| 12 | `os._exit(3)` after writing output | Exit 3 kept; no files; "no transfer received" |
| 13 | 100 KB stdout + output file | stdout cut at 65,536 and flagged; file intact |
| 14 | 9 MiB input | Refused on the Mac (exit 2) |
| 15 | Non-empty `--output` folder | Refused on the Mac (exit 2) |
| 16 | MCP, `--images stdlib,data --max-timeout 30` | pandas call with file in and back; 31 s and image `gpu` refused "(set by the server)" |
| 17 | Claude Code 2.1.289, `claude -p` with a temporary `--mcp-config` (user settings untouched) | 3 turns; used `data` and `return_files`; reported cleanup `REMOVED`; flagged the single-sample memory peak itself |
| 18 | `tools/bench.py` | stdlib median **0.316 s** per full run (20 runs); data 0.363 s (10 runs). Largest phase: arming the watcher, 0.146 s |

Afterwards: no containers or pending attempts were left; the QA profile was stopped and
deleted with `colima delete`; `~/.pybox-qa` and the scratch virtual environments were
removed. `pybox doctor` on the real installation still showed its VM stopped.

## Found and fixed during live testing

- **Watcher too sparse for short programs on long deadlines.** Spreading 64 samples
  evenly over a 10 s deadline gave a pandas run one early sample (4.7 MiB). Now the first
  20 samples are always 0.05 s apart and only the rest spread out; the same run showed
  42.4 MiB.
- **The committed `data` image was untagged.** `docker image ls` didn't list it, and
  untagged images are what `docker image prune` removes. Commits now tag it
  `pybox-data:<recipe prefix>`; runs still use the image ID. This change is unit-tested
  only (the throwaway installation had already been deleted).
- **MCP responses carry their JSON twice.** Returned files are bounded by encoded size
  (48 KiB) and dropped largest-first if a response would exceed 256 KiB.

## Limits and honest notes

- Returned files and the transfer itself are produced by a helper running as the
  program's own user. A program can forge its outputs or alter its copies of inputs. It
  cannot reach the Mac's files, and the host enforces every name, size and count of returned files. (Corrected in M10: the list of *skipped* names was not checked; it now is. See [M10_SECURITY_REVIEW.md](M10_SECURITY_REVIEW.md).)
- Live counters can miss the end of a short program (a 300 MiB allocation showed 147 MiB
  in one run). The receipt says final counters are unknown.
- The package list is fixed; there are no user-chosen images. (M10 added both matplotlib and your own images; see [M10_RESULTS.md](M10_RESULTS.md).)
- Not done: a second Mac; Claude Desktop and the official SDKs; publishing to PyPI
  (needs the owner's PyPI project and trusted publisher); the Homebrew tap; running the
  GitHub workflows (needs a push).
- Unit tests: **198 passing** (22 new in `tests/test_m9.py`; one existing assertion in
  `tests/test_container.py` changed from "3 s is rejected" to "above 30 s is rejected").
  `pybox/runner.py`, `_cpu_bootstrap.py`, `tests/test_runner.py` and
  `tests/test_cpu_limit.py` are unchanged.
