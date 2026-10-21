# M10 results — ready to share

Date: 21 October 2026. The owner asked for everything recommended after M9 except testing
on a second Mac: matplotlib, your own images, accurate final readings, a faster watcher,
tests with Claude Desktop and Cursor, an independent security review, and shipping. Nothing
was pushed or published; the owner is asked before each.

## What was built

| Item | Where |
| --- | --- |
| matplotlib 3.11.2 (+ contourpy, cycler, fonttools, kiwisolver, packaging, pillow, pyparsing) in `data`, hash-locked; `MPLCONFIGDIR=/tmp/matplotlib` | `pybox/images/data.lock`, `boxes.DATA_CHANGES` |
| Your own images: `pybox image build NAME --lock FILE`, `image list`, `image rm`; strict lock validation (exact pins with SHA-256 only); saved private recipe; data limits; receipt note about start-up code | `boxes.check_lock`, `runtime_setup.build_image`, `container.resolve_box`, `__main__._image` |
| Final readings: opt-in runs use the helper, which pauses 0.12 s (or one sampling gap) after the program, never past the deadline | `boxes.opt_in`, `linger_for`, `BOOTSTRAP` |
| Faster watcher: allowlisted direct `ssh -F /dev/null` over Lima's open connection, fallback `colima ssh`; transport on the receipt | `container._lima_ssh_settings`, `_observer_transport` |
| Review fixes (14 findings, 11 doc overclaims) | see [M10_SECURITY_REVIEW.md](M10_SECURITY_REVIEW.md), "Resolution" |
| Atomic, quarantined output writes | `transfer.OutputTarget`, `write_outputs` |
| Commits: M9 baseline `97de043` on branch `m9-useful-for-real-work`; M10 on top | git |

The default run (stdlib, at most 2 s, no files) is unchanged: same image, limits, PID 1
command, tmpfs and policy; a unit test pins its `docker create` arguments exactly.

## Live evidence

A second throwaway installation (`HOME=~/.pybox-qa`) was set up from nothing with the
`data` image in **3 min 46 s**, used, then deleted (`colima delete`, folder removed). The
real installation and its sentinels were never touched.

| Check | Result |
| --- | --- |
| Custom image from `uv pip compile --generate-hashes` (tabulate, rich, pyyaml; 6 pins) | Built in 4.5 s; ran; receipt `image_note` present |
| matplotlib chart | PNG returned (512×384) |
| 300 MiB array in `data` | Peak 327.6 MiB (146.8 MiB before final readings) |
| Exit 3 at 9.6 s of a 10 s deadline | Exit 3, `TARGET_EXIT_OBSERVED`, no deadline |
| Hostile output names (escapes, newline, invalid UTF-8, link to `/etc`) | Receipt intact, names escaped, linked folder listed |
| `A.txt` + `a.txt` | Refused; no output folder created |
| Quarantine | `0081;…;PyBox;` on returned files |
| Watcher transport | `ssh`; 4–9 ms per connection vs 0.143 s for `colima ssh` |
| Benchmark (after fixes) | stdlib median **0.204 s** (0.177–0.391, 20 runs); data 0.321 s (10 runs, includes the 0.12 s pause) |
| Cursor command-line agent, scratch workspace with `.cursor/mcp.json` and an MCP-only permission allowlist | Two sessions: chart in `data` (13,796 and 21,232 bytes); table from the custom image; all `REMOVED`. Without the allowlist, headless Cursor refused the tool call |
| Claude Desktop | **Not tested.** The owner approved a config change, and the config was backed up, edited and restored byte for byte, but Claude Desktop loads MCP servers only at start-up and this session runs inside it, so it could not be restarted. No restart happened |

## Independent review

A separate session reviewed the M9/M10 surface adversarially, without VM access. It found
no way to reach Mac files, the network, or past the server's ceilings; it found 2 Medium,
6 Low and 6 Info findings and 11 doc overclaims. All were fixed or documented with
regression tests, then re-checked live.

## Tests and known issues

- **209 tests pass.**
- The frozen native runner failed intermittently with `process-group check failed:
  [Errno 1] Operation not permitted`: locally under load, and on GitHub's macOS runners
  (Python 3.11) in 1–2 tests per run. Cause, confirmed by experiment: macOS answers
  `killpg(pgid, 0)` with `EPERM` while a group holds only unreaped zombies. With the
  owner's approval, `pybox/runner.py` now keeps checking on `EPERM` and reports it only if
  the group outlasts the cleanup deadline (12 lines; `tests/test_runner_zombies.py`).
- Not done: a second Mac; Claude Desktop; the official SDKs; PyPI publishing and GitHub
  Pages (need the owner); pinning Lima's host key for the watcher (review M10-12).

## Released

On 21–22 October 2026, with the owner's approval at each step:

- **GitHub:** `ctxnn/pybox` made public, with a single clean commit on `main` (no earlier
  history, so no personal paths), authored with the GitHub no-reply address. Private
  vulnerability reporting is on.
- **Docs site:** live at https://ctxnn.github.io/pybox/ via the Pages workflow.
- **CI:** macOS, Python 3.11–3.13, green. Two fixes were needed: the macOS zombie-group
  `EPERM` in the native runner, and a floating-point rounding error in a recorded step
  budget.
- **PyPI:** the name `pybox` is held by an empty project, so the package is
  [`pybox-sandbox`](https://pypi.org/project/pybox-sandbox/). The command and import stay
  `pybox`. Release `v0.3.0` was published by the release workflow through trusted
  publishing (no stored token), then installed from PyPI into a clean environment and
  run (`pybox --version`, `import pybox`, `pybox doctor`).
- **Homebrew:** the formula in `packaging/homebrew/pybox.rb` points at the PyPI sdist
  with its SHA-256. A tap repository has not been created.

