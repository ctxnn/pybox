# M9 plan — useful for real work

Status: **approved and implemented** (21 October 2026); see [M9_RESULTS.md](M9_RESULTS.md).
The owner chose: build all items, live tests in a throwaway installation, `pybox exec`,
Apache-2.0. Nothing is pushed or published without a separate yes.

## Why

PyBox runs one standard-library program for at most 2 seconds, with no files in or out.
That proves the safety story but blocks most real work: data needs numpy or pandas,
programs read inputs and produce results, and many jobs take longer than 2 s. The CLI
prints raw JSON, agents need hand-written setup, and installing needs a clone.

## What stays the same

- The default run keeps exactly today's box: the same image, limits, PID 1 command and
  policy check, so the M3–M5 evidence still describes it.
- Every new capability is opt-in per run and visible on the receipt.
- No host folders are ever shared with the VM or box. Files travel only as bounded copies.
- `pybox run FILE` stays the explicitly unsafe native runner (frozen tests depend on it).

## Work items

### 1. Images with common packages (`--image`)

| Image | Contents | Memory | CPU | Default |
| --- | --- | --- | --- | --- |
| `stdlib` | The pinned `python:3.13-slim` digest (today's image) | 128 MiB | 0.5 | yes |
| `data` | The same base plus numpy and pandas (and their dependencies), exact versions with `pip --require-hashes` | 512 MiB | 1.0 | opt-in |

- `pybox setup --yes --with data` builds `data` inside the VM from a recipe shipped in the
  package. This is the only time the VM uses the network for packages; runs keep `--network=none`.
- A locally built image has no registry digest, so setup records its image ID in a private
  file (`~/.pybox/runtime/images.json`). Every run checks the box against that ID and the
  recipe's SHA-256, and the receipt shows both.
- The policy check gets a per-image table (memory, CPU, PIDs, tmpfs), still compared field by field.

### 2. Files in and out (`--input`, `--output`)

- `--input PATH` (files or a folder, repeatable): copies are sent in on standard input and
  appear at `/tmp/input/` in the box. Limits: 64 files, 8 MiB in total.
- `--output DIR`: the program writes to `/tmp/output/`; PyBox brings back regular files only,
  with names checked, never following links, never overwriting. Limits: 64 files, 8 MiB.
  `DIR` must be new or empty.
- How: only when files are used, PID 1 runs a small fixed bootstrap (`python -I -B -u -c
  <fixed script>`, verified like today's command) that unpacks the inputs, runs the
  program, then appends the outputs after a per-run boundary on standard output.
- Honest labelling: outputs are made by the untrusted program, so the receipt marks them
  untrusted (like stdout). A program could tamper with its own copies or the transfer;
  it still can't reach your Mac's files, and the host side enforces every bound.
- The scratch tmpfs grows from 16 MiB to 64 MiB only for runs that move files.

### 3. Longer runs (`--timeout` up to 30 s)

- Default stays 2 s. Anything above it is an explicit choice, shown on the receipt.
  The box timer stays limit + 1 s; expiry (120 s) still covers the longest run plus cleanup.
- For MCP, the person configuring the server sets the ceiling (`pybox mcp --max-timeout 30`);
  an agent can only ask for less.

### 4. `pybox exec` and a readable receipt

- `pybox exec script.py` (or `-` for standard input) runs in the sealed box and prints a
  short receipt in the terminal, grouped like the site: engine, kernel, program, unknown.
- `--json` prints the full versioned record (today's `container --inspect`).
- `pybox container` stays for compatibility.

### 5. AI agents first

- `run_python` gains optional `image`, `files` (name → text or base64) and `return_outputs`.
  Outputs come back inside the result as data.
- `pybox mcp --max-timeout N --images stdlib,data` lets the human set what agents may use.
- One-line setup documented and tested: `claude mcp add pybox -- pybox mcp`, plus the Claude
  Desktop config. Live check: a headless Claude Code session (`claude -p` with the MCP config)
  runs code through PyBox.

### 6. Install

- Publish-ready package: `pyproject` metadata, licence field (pending your choice), README
  for PyPI, sdist and wheel built and installed in a clean venv and with pipx.
- `.github/workflows/release.yml` using PyPI trusted publishing. You register the project on
  pypi.org; I can't enter credentials.
- Homebrew formula template, ready once a PyPI release exists.
- `pybox setup --yes` prints a timed summary and the exact next steps; `pybox doctor` gets a
  readable view (JSON behind `--json`).

### 7. Speed

- `tools/bench.py`: N runs, time per phase (admission and reconcile, create, readback,
  watcher, run, removal). Publish the numbers on the site.
- Take cheap wins only if they keep every check. A pool of pre-built boxes is **not** planned:
  it breaks "fresh every time". It's documented as a trade-off.

### 8. Documentation

New site pages: Images, Files in and out, Longer runs, `pybox exec`, Claude Code and Claude
Desktop, Performance. Plus updates to install, CLI, MCP, reference, FAQ, README, ROADMAP,
PROGRESS and `M9_RESULTS.md`.

## Live testing

The real installation on this Mac holds two sentinel containers that a run would reconcile.
The proposal is a **throwaway installation**: `HOME=~/.pybox-qa` gives a separate runtime,
VM, owner and images, set up from scratch. That doubles as the first fresh-install check
since M8. Afterwards: `colima delete` for that profile, then delete the folder. The real
installation and its sentinels are never touched. Needs about 1 GB of downloads and roughly
15 minutes.

## Not in M9

Linux or Intel hosts, networked runs, arbitrary user images, GPU, background runs or queues,
a pool of pre-built boxes, publishing anything without your yes.
