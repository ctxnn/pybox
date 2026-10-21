# M10 security review: files, images, linger and the direct-ssh watcher

Date: 21 October 2026. Reviewer: an independent Claude Code session, started by the main
M10 session. This file is the only change it made. It ran no VM, no `pybox exec`, `setup`,
`image`, `vm` or `cleanup` command, no benchmark or validation tool, and made no network
calls.

## 1. Scope and method

**Scope.** The diff from `1e07a74` to the working tree on `m9-useful-for-real-work`
(including uncommitted M10 edits), limited to what M9 and M10 add:

- `pybox/boxes.py`: `BOOTSTRAP`, `frame`, `split_outputs`, `check_name`, `check_files`,
  `check_lock`, `linger_for`, `opt_in`, `make_box`
- `pybox/transfer.py`
- `pybox/container.py`: `local_images`, `resolve_box`, `read_recipe`, `expected_recipe`,
  `_create_args`, `_check_policy`, `_observer_transport`, `_Observer`, `run_container`
- `pybox/runtime_setup.py`: `build_image`, `_save_recipe`, `_write_private`,
  `remove_image`, `list_images`, doctor changes
- `pybox/mcp.py`, `pybox/mcp_policy.py`: `image`, `files`, `return_files`, server
  `--max-timeout` / `--images`, `deliver_outputs`, `fit_result`, worker argv
- `pybox/__main__.py` (`exec`, `image`), `pybox/receipt.py`, `pybox/inspection.py`
  (record shape), `pybox/_observe.sh` (interval argument)
- Docs: `docs-site/pages/files.html`, `packages.html`, `mcp.html`, `performance.html`,
  `docs/M9_RESULTS.md`

The M3–M7 code was covered by `docs/M7_FINAL_REVIEW.md` and was not re-reviewed.

**Threat model.** The Python program is hostile, and so is everything it prints, writes
or names, including what the in-box helper sends back (the helper runs as the program's
user). MCP clients and agents are untrusted callers. The person running PyBox, and
files only they can write, are trusted.

**Method.** I read every function in scope. Then I tested the host-side code directly
with small scripts in a scratch folder outside the repo:

- `boxes.split_outputs`, `transfer.write_outputs`, `mcp_policy.project_record`,
  `mcp_policy.encode` and `receipt.render`, fed with crafted transfers.
- `BOOTSTRAP` run locally under `python -I -B -c`, with `/tmp` rewritten to a scratch
  folder.
- The `_observer_transport` config check, run against crafted `ssh.config` files and
  compared with `/usr/bin/ssh -G -F <file>`. That command only prints the evaluated
  config (OpenSSH 10.3p1) and connects to nothing.

The unit suite passes: `python -B -W error::ResourceWarning -m unittest discover -s tests`
ran **203 tests, OK**.

Severity reflects this prototype's threat model. "Medium" means a hostile program or
agent can defeat a property PyBox advertises (here, the honesty of the receipt). It does
not mean the program can reach the Mac. **I found no way for the program or an agent to
read or write Mac files outside the chosen output folder, escape the box, reach the
network, or exceed the server's ceilings.**

## 2. Findings

Ranked most severe first. Line numbers are for the current working tree.

| ID | Severity | Where | What can happen | Reproduction / reasoning | Suggested fix |
| --- | --- | --- | --- | --- | --- |
| M10-01 | **Medium** | `pybox/receipt.py:104-105`, `pybox/boxes.py:90`, `:265`; `pybox/__main__.py:207-212` | **A program can forge the terminal receipt.** `outputs_skipped` holds names the program chose, and the receipt prints them raw, inside the receipt, after the trusted "From the container engine" lines. Linux file names may contain ESC, CR and LF. Cursor-up and erase-line sequences in a skipped name can overwrite earlier receipt lines on a TTY, for example turning "Box NOT CONFIRMED" into "removed and confirmed gone". Program stdout and stderr are also written raw just before the receipt, so they can leave the terminal in a hostile state (scroll region, conceal when `NO_COLOR` is set). | In the box: `os.symlink("x", "/tmp/output/a\x1b[8A\x1b[2K  Exit code             0 (ended by itself)\n  forged")`. The helper skips the link and lists its name. Checked on the host: `receipt.render` returns the row `Not brought back      ok\x1b[8A\x1b[2K  Exit code …\n  forged line` unchanged. The `--json` path is safe, because `json.dumps` escapes control characters. | Escape every untrusted string the receipt prints: replace C0/C1 controls and DEL with `\xNN` or `repr()`, or print only a count of skipped files. Consider printing the receipt only after a reset (`\x1b[0m`, and `\x1b[r` to reset the scroll region) when stderr is a TTY, and say in the receipt that program output came before it. |
| M10-02 | **Medium** | `pybox/mcp_policy.py:29-30`, `:135-147`; `pybox/mcp.py:339-348`; `pybox/boxes.py:90`, `:265` | **Over MCP, a program can replace its own receipt with a failure that falsely says cleanup is unconfirmed.** (a) A name that is not valid UTF-8 in `/tmp/output` reaches the host as a lone surrogate (`"\udcff"`), via `os.walk`, surrogateescape and `json.dumps`. `encode()` uses `ensure_ascii=False` followed by `.encode('utf-8')`, so it raises `UnicodeEncodeError` inside `project_record`. The worker's catch-all then returns "Supervisor failed; cleanup is unconfirmed" (exit 1), although cleanup did complete. (b) 64 skipped names of control characters (each becomes `\u0001`, 6 bytes, in JSON) push the record past `MAX_RECORD_BYTES`. `project_record` trims only stdout and stderr, then gives up with "Inspection metadata exceeded delivery bound; details unavailable". Either way the agent loses the trusted facts (policy readback, kernel counters, cleanup status) and the program decides when that happens. The real helper is enough for both; no forged manifest is needed. | Checked on the host: `split_outputs` accepts `"skipped":["\ud800"]`, and `mcp_policy.encode` then raises `UnicodeEncodeError`. 64 × 512 chars of `\x01` give 196,801 bytes of JSON, and `project_record` returns the failure. In the box: `os.symlink("x", b"/tmp/output/\xff")` for (a); `for i in range(64): os.symlink("x", "/tmp/output/" + "\x01"*250 + str(i))` for (b). | In `split_outputs`, keep only skipped names that are printable ASCII matching `check_name`'s alphabet, replacing anything else with a placeholder or `repr()`, and cap the list's total size (for example 4 KiB). Also bound or summarise `files.outputs_skipped` in `project_record`, as it already does for reconciliation. Make `encode` safe against lone surrogates (`errors="backslashreplace"`, or use `ensure_ascii=True`). Never let a projection error be reported as "cleanup is unconfirmed" when `execution.removed` is known. |
| M10-03 | Low | `pybox/container.py:380-381`, `:391-413` | **The `ssh.config` check is a denylist that is easy to get around.** The direct-ssh watcher runs `/usr/bin/ssh -F <Lima ssh.config>` and trusts that file once it passes a regex. OpenSSH strips quotes from keywords, so `"ProxyCommand" …` and `Proxy"Command" …` pass the regex and still set ProxyCommand. Several keywords that run code or load libraries are not on the list at all: `KnownHostsCommand`, `PKCS11Provider`, `SecurityKeyProvider`. A `Host *` block placed before `Host lima-colima-pybox` can set `Hostname 203.0.113.9` and `Port 2222`. Because ssh keeps the first value it reads, that overrides the required `Hostname 127.0.0.1` line, and the check still passes. There is also a small check-then-use gap: ssh re-reads the file after PyBox checks it. Exploiting any of this needs write access to a private file in `~/.pybox/runtime`, which already means code execution as the user, so the practical gain is small. But it is the one place where M10 hands a file's contents to a program that executes commands, and the check suggests more assurance than it gives. | For each case, the PyBox regex passed and `/usr/bin/ssh -G -F c.conf lima-colima-pybox` printed, respectively: `proxycommand /bin/echo pwned1`, `proxycommand /bin/echo pwned2`, `knownhostscommand /bin/echo pwned3`, `pkcs11provider /tmp/evil.dylib`, `securitykeyprovider /tmp/evil2.dylib`, and `hostname 203.0.113.9` / `port 2222`. | Don't pass `-F` with Lima's file. Parse it with an allowlist (`IdentityFile`, `User`, `Hostname`, `Port`, `ControlPath`, plus Lima's known benign options), require `Hostname` to be exactly `127.0.0.1` and the port a number, and run `ssh -F /dev/null -o IdentitiesOnly=yes -o IdentityFile=… -o Port=… -o User=… -o ControlPath=… -o ControlMaster=no -o BatchMode=yes 127.0.0.1 …`. If you keep `-F`, at least run `ssh -G` first and refuse when any of `proxycommand`, `proxyjump`, `knownhostscommand`, `localcommand`, `remotecommand`, `pkcs11provider`, `securitykeyprovider`, `include` or any forwarding is set, or when hostname/port differ from the values you expect. |
| M10-04 | Low | `pybox/transfer.py:68-91`; `pybox/boxes.py:204`; `pybox/__main__.py:198-203` | **Output names that differ only in case cause a partial write on macOS.** `check_files` compares names case-sensitively, but APFS is case-insensitive by default. `A.txt` and `a.txt`, or `Data` and `data/x`, are accepted, and `write_outputs` then fails with `FileExistsError` partway through. Earlier files stay on disk. Nothing is overwritten (`O_EXCL` holds), but the output folder is left half-written, contrary to the docs. | Checked on the host: the transfer `[A.txt, a.txt, z.txt]` is accepted by `split_outputs`; `write_outputs` raises `FileExistsError: 'a.txt'` and leaves `['A.txt']` behind. | In `check_files`, also reject collisions under `name.casefold()`, including the prefix/overlap check. Write into a fresh private temporary folder inside the parent (`mkdtemp`, then `O_EXCL` writes), and `rename` it into place only when every file succeeded. Or remove what was written on error. |
| M10-05 | Low | `pybox/container.py:865-867`, `:922-924`; `pybox/boxes.py:213-215` | **The linger counts against the program's own deadline.** The helper sleeps `linger_for(timeout_s)` (0.12 s at 2 s, 0.75 s at 30 s) inside the same wall deadline. A program that finishes 0.5 s before a 30 s deadline is killed during the linger: the receipt says `DEADLINE_REACHED`, exit 137, `SUPERVISOR_KILL_OBSERVED`, and the program's real exit status is lost. Every opt-in run with a 2 s deadline also loses 0.12 s of the deadline it was given. | From the code: `stdin_data` includes `linger`; the start call uses `deadline=wall_deadline = wall_start + timeout_s`; the helper's `time.sleep(h["linger"])` runs before `sys.exit(st)`. | Give the start call (and the box timer) `timeout_s + linger`. Then have the helper end its linger at the deadline, by passing the remaining budget, or send the program's exit status before lingering (for example in the transfer manifest, marked as from the helper). |
| M10-06 | Low | `pybox/runtime_setup.py:231-243`, `:265-325`, `:340-355` | **Image build and remove are not serialised, and they leave things behind on failure.** `build_image` reads `images.json`, builds for up to 15 minutes, then writes the whole dict back, without the lifecycle lock. Two concurrent `pybox image build` commands, or a build and an `image rm`, lose an update. If the process is killed, the `pybox-build-*` container (which has network access and runs as root) keeps running pip to completion. It carries no owner label, so `pybox cleanup` never sees it. `_write_private` leaves its `.pending-*` temporary file behind if `os.replace` fails. | From the code: no `_admission()` or other lock around read-modify-write; `finally: container rm --force` runs only if Python survives; no cleanup of `temporary` in `_write_private`. | Take an exclusive `flock` on `images.json` (or the lifecycle lock) for the read-modify-write. Re-read the record just before writing. Label build containers with the installation owner, and let `cleanup` report or remove stopped `io.pybox.build` containers. Unlink the temporary file in a `finally`. |
| M10-07 | Low | `pybox/transfer.py:55-65`, `:71` | **The output folder is checked once and opened again later.** `prepare_output_dir` checks for "new or empty" before the run; `write_outputs` re-opens the path up to about 70 s later. `O_NOFOLLOW` protects only the last component. If a parent folder is writable by someone else (a shared folder, `/tmp/…`), that person can swap a parent for a symlink in between and redirect the writes. The folder is also not re-checked for emptiness, so existing subfolders are merged into. | From the code; the trusted user picks the path, so this needs another local user and a shared parent. | Open the folder once in `prepare_output_dir` (`os.open(…, O_DIRECTORY \| O_NOFOLLOW)` after `mkdir`), keep the descriptor for `write_outputs`, and re-check emptiness on that descriptor before writing. |
| M10-08 | Low | `pybox/transfer.py:85` | **Returned files carry no quarantine attribute.** Files the program made land on the Mac as if the user had created them. Some file types act when opened, even without the execute bit. A Terminal settings file (`report.terminal`) can carry a command to run; `.fileloc` and `.webloc` open targets. Gatekeeper only checks such files when they carry `com.apple.quarantine`. | From the code: files are written `0644` with no extended attributes. Output names allow any extension. | Set `com.apple.quarantine` on each written file (via `xattr` or `setxattr`, e.g. `0081;<hex time>;PyBox;`), or refuse a short list of extensions that act when opened. Mention this on the files page. |
| M10-09 | Info | `pybox/boxes.py:49-98` | **The run marker is not secret from the program.** The helper's state, `h` (including `boundary` and `linger`), is reachable from the program: `sys._getframe(0).f_back.f_globals["h"]`. So the program can print a valid-looking transfer, set the linger to 0, or replace `os.walk`. This matches the stated model ("a program could fake its own outputs"), and the host checks hold regardless. Readers may still take "random marker unique to this run" to mean the program can't produce it. | Run locally under the real `BOOTSTRAP`: the program printed `boundary seen by program: c0ffee…ab`. | Docs only: say the marker separates output from the transfer by accident, not against the program. Optionally `del h` before `exec` and keep only locals the program can't reach. That makes accidents less likely, not forgery impossible. |
| M10-10 | Info | `pybox/runtime_setup.py:290-291`; `pybox/container.py:278` | **For your own images, locked packages can run code before the "fixed helper".** Wheels can't run code at install time (`--only-binary=:all: --require-hashes`), but they can ship `.pth` files or `sitecustomize`, and `python -I` still imports `site`. Such code runs as uid 10000 in the box before `BOOTSTRAP`, so the claim that a fixed, checked helper ran is not true for those images. Host safety is unaffected, because everything the box returns is untrusted already. | From CPython's `-I` semantics (`-I` implies `-E -s` but not `-S`). | State it in the record or receipt for non-built-in images ("site-packages may run code before the helper"), or start the box with `-S` and add site-packages to `sys.path` inside the helper. |
| M10-11 | Info | `pybox/boxes.py:79-90` | **Some things in `/tmp/output` are dropped without being listed.** `os.walk` puts symlinks to folders in `dirnames` and never lists them as skipped; empty folders are dropped too. Files written by non-daemon threads or `atexit` handlers after the program's main code returns are missed, because the helper packs before interpreter shutdown. | Run locally: `/tmp/output/etcdir -> /etc` plus `pw -> /etc/passwd` gave `"skipped": ["pw"]`. | List symlinked folders in `skipped`. Document that packing happens when the main module returns, before threads and `atexit` finish. |
| M10-12 | Info | `pybox/container.py:411` | **The direct-ssh path inherits Lima's host-key settings.** Lima's config uses `StrictHostKeyChecking no` and `UserKnownHostsFile /dev/null` for `127.0.0.1:<port>`. A local process that holds that port (another Mac user during a VM restart, before the hostagent rebinds it) could answer as the VM and feed made-up "kernel" readings into the trusted section of the receipt. `colima ssh` has the same property, so M10 doesn't make this worse. | Reasoning from Lima's generated config. | If you parse the config (M10-03), pin the VM's host key, which Lima records, with `UserKnownHostsFile=<private file>` and `StrictHostKeyChecking=yes`. |
| M10-13 | Info | `pybox/runtime_setup.py:265-283` | `build_image("stdlib", lock=…)` is accepted from Python (only the CLI refuses built-in names). It records an image that `resolve_box` never uses, and `image list` then shows two `stdlib` rows. | From the code. | Reject `boxes.BUILT_IN` names other than `data` in `build_image` itself. |
| M10-14 | Info | `pybox/mcp.py:135`; `pybox/container.py` budgets | The supervisor deadline (`45 + max_timeout − 2` = 73 s at 30 s) leaves under 1 s of headroom over the worst-case sum of phase budgets (15 + 5 + 2 + 1 + 30 + 2 + 15 + 2.1 ≈ 72.1 s). That is the same margin as at 2 s, so it is consistent, but any new phase or budget will tip slow runs into "Supervisor deadline exceeded; cleanup is unconfirmed". | Arithmetic over `OPERATION_TIMEOUTS`, `CLEANUP_BUDGET_S`, `_Observer.finish`. | Derive `WORKER_DEADLINE_S` from the same constants, and add a unit test that pins the margin. |

## 3. Doc overclaims

| Page | Claim | What the code does |
| --- | --- | --- |
| `docs-site/pages/files.html` | "It writes nothing unless everything checks out." | Parsing is all-or-nothing, but writing isn't: a case-only name collision on APFS writes some files, then fails (M10-04). |
| `files.html` | "Links and special files … Skipped and listed." | Symlinks to folders and empty folders are dropped without being listed (M10-11). The list itself comes from the program and is printed raw (M10-01). |
| `files.html` | "Runs the program exactly as `python -` would." | Close, but the helper's globals can be reached from the program (M10-09); packing happens before threads and `atexit` finish (M10-11); with your own images, `site` code runs first (M10-10); and the linger eats into the deadline (M10-05). |
| `files.html` | "Its exact code is part of the settings PyBox checks before starting." | True for the command line (`Cmd` is compared byte for byte). But that doesn't mean the helper ran unmodified: for your own images see M10-10, and the program can rewrite the helper's state while it runs (M10-09). |
| `files.html` | "after a random marker unique to this run" | Accurate, but the program can read the marker (M10-09). Worth one sentence. |
| `docs-site/pages/packages.html` | "The same base plus numpy 2.5.4, pandas 3.0.6, python-dateutil, six and tzdata." | `pybox/images/data.lock` now also pins matplotlib 3.11.2, contourpy, cycler, fonttools, kiwisolver, packaging, pillow and pyparsing. The CLI `--with` help and the MCP tool description still say "numpy, pandas". |
| `packages.html` | "The package list is fixed; you can't add your own packages yet." | M10 adds `pybox image build NAME --lock FILE`. Also out of date: `docs/M9_RESULTS.md` ("there are no user-chosen images") and `mcp.html` (`--images` lists only `stdlib`, `data`). |
| `packages.html` | "Before every run, PyBox checks … that the recipe hasn't changed since it was built." | It checks that the recipe hash in the private `images.json` matches the current recipe (shipped, or the private `recipes/<name>.lock`). Both are local records. Nothing inside the image proves which recipe built it; the image ID only pins its content. The wording is fair if it says "the recorded recipe". |
| `docs-site/pages/mcp.html` | "`execution` is the receipt" and "64 KiB of receipt". | A hostile program can turn the receipt into a generic failure that says cleanup is unconfirmed (M10-02). |
| `docs-site/pages/performance.html` | "Arm the watcher … 0.146 s … A long-lived watcher could shave that off … future work." | Measured before the M10 direct-ssh transport, which the code docstring says takes "about 5 ms". Neither figure has evidence for the current code yet, and the receipt does not show which transport was used (only the raw `operations[].transport` does). Re-measure, and say which transport each number used. |
| `docs/M9_RESULTS.md` | "the host enforces every name, size and count." | True for names, sizes and counts of returned files. Not true for the skipped list, whose names are not checked (M10-01, M10-02). |

## 4. Checked and found sound

- **No path out of the output folder.** `check_name` allows 1–4 parts of
  `[A-Za-z0-9_][A-Za-z0-9._-]{0,127}`, so no `..`, no leading dot, no absolute paths, no
  NUL and no non-ASCII. `write_outputs` walks with `dir_fd`, `O_DIRECTORY|O_NOFOLLOW` on
  every folder and `O_CREAT|O_EXCL|O_NOFOLLOW` on every file, so it never follows a link
  and never overwrites. Modes are `0644`/`0755` whatever the box used, so no execute bits
  come back.
- **Transfer parsing is strict and bounded.** The marker is found with `rfind`; the
  manifest must have exactly the `files` and `skipped` keys; there must be one payload
  line; base64 is decoded with `validate=True`; sizes must be non-bool ints that add up
  exactly; then `check_files` re-applies the 64-file and 8 MiB caps. Odd shapes I tried
  (dict entries, strings, negative or bool sizes, sizes that don't add up, trailing
  output) are all rejected without returning files. Host capture is capped at
  `max_output_bytes + OUTPUT_WIRE_CAP` (about 11.3 MiB), and the program part is cut back
  to `max_output_bytes` before it is stored in the record and the operations log.
- **Input collection** refuses symlinks at the top level and inside folders, opens with
  `O_NOFOLLOW|O_NONBLOCK`, checks `S_ISREG` on the open descriptor (so FIFOs and devices
  are refused without blocking), and charges every read against the 8 MiB budget before
  reading further.
- **`check_lock` / build.** Only `name==version --hash=sha256:<64 hex>`+ lines survive,
  and the normalised text (not the raw file) is what reaches pip. There is no way to
  express an option, URL, path, extra, environment marker, `===`, wildcard or `${VAR}`.
  pip runs with `--require-hashes --only-binary=:all:`, so every dependency must be
  pinned too and no sdist build code runs. The install command is a constant string; the
  lock arrives on stdin. Names are validated (`IMAGE_NAME`) before they reach a label or
  file name.
- **docker / colima / ssh argv.** Nothing in any argv comes from an agent or the program.
  Image refs are the pinned digest or a validated `sha256:<64 hex>` from the private
  record. Names and labels come from `_identity`; the container ID is checked against 64
  hex characters; `timeout_s` is a validated float; the observer interval is formatted
  `%.2f` and re-checked by `_observe.sh` (`[0-9].[0-9][0-9]`). `shlex.join` correctly
  quotes the single remote command string for the guest shell.
- **Per-box policy check.** `_check_policy` compares memory, swap, PIDs, CPU, tmpfs
  options, image ref and the full PID 1 command (bootstrap included) against the
  resolved `Box`. The rest of the baseline (network none, read-only root, cap-drop ALL,
  no-new-privileges, user, ulimits, no binds, mounts, devices or ports) is identical for
  every box. An image-declared `VOLUME` would show up as a non-tmpfs mount and be
  refused. Unknown image names get the `data` limits, never anything larger.
- **Private records.** `images.json` and `recipes/*.lock` are opened with `O_NOFOLLOW`
  and checked to be owned by you, mode `0600`, with one link and a bounded size. Every
  entry's name, ID, base and recipe hash is validated. `_write_private` replaces files
  atomically under umask `077`.
- **MCP ceilings.** `timeout_s` is checked against the server's `--max-timeout` in the
  server and again in the worker (bools, NaN and infinity rejected). `image` must be in
  the server's list. `run_container` independently caps at 30 s and validates the image
  name. `files` is capped at 16 entries and 256 KiB decoded, inside a 512 KiB frame. An
  agent cannot name a host path, an environment variable, the unsafe runner or the
  output folder; MCP never writes files to the Mac. Returned contents are bounded at
  48 KiB encoded, and `fit_result` drops the largest until the response fits 256 KiB.
  The worker's argv comes only from the server's validated settings.
- **CLI ceilings.** `--max-timeout` must be in (0, 30], with NaN and infinity refused;
  `--images` names are validated; `exec --timeout` above 30 s is refused before any box
  is built.
- **Default run unchanged.** With `stdlib`, at most 2 s, and no files, `opt_in` is false:
  PID 1 runs `python -I -B -u -`, with no bootstrap, a 16 MiB tmpfs and no linger. A unit
  test pins these `docker create` arguments.
- **Unit tests:** 203 pass on the working tree.

## Not covered

No live runs: no VM, Docker or Lima behaviour was exercised, including how ssh
ControlMaster/ControlPersist behaves when PyBox's ssh becomes the master. pip's
behaviour was taken from its documented semantics, not run. The M3–M7 lifecycle,
reconciliation and native runner were out of scope.

## Resolution (main M10 session, 21 October 2026)

Every finding was addressed before release. Regression tests are in `tests/test_m9.py`
(`ReviewFixTests`, `ObserverTransportTests`, `TransferTests`), and the fixes were re-checked
live in a throwaway installation.

| ID | Resolution |
| --- | --- |
| M10-01 | Fixed. `boxes.safe_names` keeps skipped names printable ASCII (others become `\xNN`), at most 128 characters each and 4 KiB in total. `receipt._clean` escapes every value the receipt prints. On a TTY the receipt starts with `\x1b[0m\x1b[r`. Live: escape and newline names printed escaped; receipt intact. |
| M10-02 | Fixed. Skipped names are sanitized at parse time. `encode` uses `backslashreplace`. `project_record` lists at most 16 skipped names. A delivery failure now reports the run's real cleanup status and `removed`, not "supervisor failed". |
| M10-03 | Fixed. PyBox no longer passes Lima's file to ssh. `_lima_ssh_settings` parses it with an allowlist (one exact `Host` block, Lima's 16 keywords, no quoted or `=` keywords, no duplicates), requires `Hostname 127.0.0.1`, a numeric port, this user, and the expected key and socket paths. It runs `ssh -F /dev/null` with those four values plus fixed options, including `ControlMaster=no`. Every bypass in the finding is a unit test that now falls back to `colima ssh`. |
| M10-04 | Fixed. Collisions are checked under `casefold()`. Outputs are written into a fresh hidden folder next to the target and renamed into place only when complete; on any error it is removed. |
| M10-05 | Fixed. The helper caps the pause at `deadline − elapsed − 0.25 s`. Live: exit 3 just before a 10 s deadline was kept, with no deadline fired. |
| M10-06 | Fixed. Builds and removals hold `images.lock`, and the record is re-read just before writing. Build containers carry `io.pybox.build-owner`; stopped ones left by a crash are removed at the next build. `_write_private` removes its temporary file on failure. |
| M10-07 | Fixed. `OutputTarget` opens the parent once before the run; staging, writes and the final rename all go through that descriptor. The rename fails rather than merge if the folder filled up. |
| M10-08 | Fixed. Each returned file gets `com.apple.quarantine` via `fsetxattr` on its open descriptor. |
| M10-09 | Documented: the marker separates output from the transfer; it is not a secret from the program (files page). |
| M10-10 | Documented on the receipt (`configured.image_note`) and the packages page. |
| M10-11 | Fixed for symlinked folders (now listed). Documented: packing happens when the main code returns, and empty folders are dropped. |
| M10-12 | Unchanged, as in `colima ssh`: same host-key policy, documented in the transport docstring. Pinning Lima's host key is future work. |
| M10-13 | Fixed: `build_image` refuses `stdlib`. |
| M10-14 | Fixed: `mcp.worker_deadline` derives the deadline from the engine's budgets (worst case plus 5 s above a 2 s ceiling; unchanged at 2 s), with a test. |
| Doc overclaims | All 11 corrected in `files.html`, `packages.html`, `mcp.html`, `performance.html` and `docs/M9_RESULTS.md`. |

