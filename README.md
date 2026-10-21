# PyBox

**Run Python you don't trust in a fresh, sealed box on your Mac — and get a
receipt that says how it knows what happened.**

You give PyBox a program. It runs it once in a brand-new Linux container inside a
private VM: no network, no access to your files, a read-only system, strict memory,
CPU and process limits. Then it removes the box and hands you a receipt that keeps
four kinds of fact apart: what was *configured*, what the engine and kernel
*observed*, what the program *printed*, and what is still *unknown*.

When a job needs more, you ask for it on that run, and the receipt shows it:
**numpy, pandas and matplotlib** (the `data` image), **your own pinned packages**,
**up to 30 seconds**, and **copies of files in and out**. The same engine works from the command line, from Python, as an
**MCP tool for AI agents** (`claude mcp add pybox -- pybox mcp`), and in a bounded
AI repair loop where the model can only propose code.

> [!IMPORTANT]
> **Status: research prototype, Apple Silicon Macs only.** PyBox creates its
> sealed runtime in your own home (`~/.pybox/runtime`) with `pybox setup`, after
> showing you exactly what it will do. Every claim is backed by dated, recorded
> runs on the machine it was built on. A fresh setup from nothing has been run in
> a separate, throwaway installation on that Mac (21 October 2026), **but not yet
> on a second Mac**. Linux and Intel Macs are not supported; PyBox refuses to run
> there rather than run unsealed. It is not certified for hostile code from the
> public internet.

## Quickstart

Requirements: macOS on Apple Silicon, **Python 3.11 or newer**, and
`brew install colima docker`. PyBox has no Python dependencies and never installs
software for you.

```bash
pipx install pybox-sandbox
```

Or `python3 -m pip install pybox-sandbox`, or from a clone: `python3 -m pip install .`.
The package is called `pybox-sandbox` on [PyPI](https://pypi.org/project/pybox-sandbox/)
because the name `pybox` was taken; the command is `pybox` and the import is `import pybox`.

### Set up once

```bash
pybox setup              # dry run: shows every folder, file and download first
pybox setup --yes        # about 3–5 minutes, mostly the one-time VM download
pybox setup --yes --with data   # optional: numpy, pandas, matplotlib, about 30 s
pybox doctor             # read-only check; says what to run next
```

Setup creates a private `~/.pybox/runtime`, starts a dedicated Colima profile
`pybox` (no host folders, no forwarded ports), pulls **only** the pinned Python
image by digest, verifies it, and stops the VM. It never overwrites a file. The
`data` image is built in the VM from hash-locked wheels; it is the only time a
PyBox container has the network.

### Run things

```bash
pybox vm start
echo 'print(6*7)' | pybox exec -
pybox exec report.py --input sales.csv --output results/
pybox exec analysis.py --image data --timeout 20
pybox image build tools --lock tools.lock   # your own packages, from uv pip compile --generate-hashes
pybox vm stop
```

`pybox exec` prints the program's output, then a short receipt (to stderr):

```text
42

PyBox receipt · run 5319e024 · image stdlib · 0.166 s of 2 s

From the container engine  checked before start, read back after
  Exit code             0 (ended by itself)
  Settings checked      yes, before the program started
  Mac folders shared    none
  Network               none
  Limits                128 MiB · 32 processes · 0.5 CPU · 2 s (+1 s box timer)
  Box                   removed and confirmed gone

From the Linux kernel  sampled while it ran, from outside the box
  Memory peak           2.5 MiB of 128 MiB
  Processes peak        6 of 32
  CPU throttled         0 periods

From the program  untrusted: a program can print or write anything
  Printed               3 bytes on stdout, 0 bytes on stderr

Not known  PyBox says so instead of guessing
                        final counters (the box can vanish between readings) · exact clock alignment
```

`--json` prints the full versioned record instead. A complete fresh-box run takes
about **0.2 s** once the VM is running ([performance](site/performance.html)).
Returned files are written all at once, never overwrite anything, and are marked
like downloads so macOS checks them when opened.

### With an AI agent

```bash
claude mcp add pybox -- pybox mcp --images stdlib,data --max-timeout 30
```

The agent gets one tool, `run_python`, with optional `image`, `files` and
`return_files`. You set the ceilings; the agent can only ask for less. Program
output and returned files come back as data inside the result, never as protocol
messages. Tested with PyBox's own MCP client, Claude Code and Cursor's command-line
agent; not yet with Claude Desktop ([details](site/mcp.html)).

### From Python

```python
from pybox import run_container

result = run_container(open("report.py").read(), image="data", timeout_s=10,
                       inputs=[("sales.csv", open("sales.csv", "rb").read())],
                       collect_outputs=True)
print(result.record["cleanup"]["status"], [name for name, _ in result.output_files])
```

### Tests

```bash
python3 -B -W error::ResourceWarning -m unittest discover -s tests
```

Expect `Ran 209 tests … OK`. They mock the engine and never start the VM.

> [!WARNING]
> **On the originally qualified Mac only:** every run and `pybox cleanup` first
> reconciles this installation's leftovers, which removes the deliberately retained,
> now-expired sentinel container kept as Step 4 evidence. To keep it, use a
> separate installation (`HOME=…`), as the M9 live tests did.

## What PyBox promises — and what it does not

| Promise | Evidence (dated, local) | Limit |
| --- | --- | --- |
| Each run uses a fixed policy the caller cannot change: pinned image, UID 10000, all capabilities dropped, no-new-privileges, no network, read-only root, noexec `/tmp`, memory = memory+swap, task, CPU and file limits, no engine logs. The policy is read back and verified **before START**. | 13 restriction checks (M3b), 9 resource checks (M3c) | Finite checks, not proof against arbitrary hostile code. |
| Opt-in choices are fixed options, verified like everything else: the `data` image or your own (512 MiB, 64 tasks, 1 CPU, checked by image ID and recipe hash), deadlines up to 30 s, files copied in and out within 64 files / 8 MiB each way. | 18 live checks (M9), 11 more (M10), an independent security review | Returned files are the program's work and untrusted. Your own packages can run start-up code inside the box. |
| Execution ends even if the Mac supervisor is killed: PID 1 is a kill timer set to the wall deadline + 1 s. | Supervisor `SIGKILL` → stopped at 3.028 s; 30 s run stopped at 30.01 s | Assumes a healthy, scheduled VM. Not a hard real-time bound. |
| Leftovers are reclaimed by the next run or `pybox cleanup`, only after expiry (120 s), only if stopped and fully identity-matched. | Step 4 real-expiry reclamation | Without another invocation, stopped objects stay indefinitely. |
| Resource facts come from the kernel (cgroup v2), read by a trusted reader outside the container — never from program output. | OOM kill, task-limit and throttling events observed (M3c, M4) | Live samples, not exact finals; clocks are not aligned. |
| MCP: one tool, bounded inputs, output nested as data. | 13 live protocol checks (M5); Claude Code and Cursor sessions (M9, M10) | Not tested with Claude Desktop or the official SDKs. |
| Repair loop: the model returns a full-source proposal; trusted code decides everything else. | 8 real sessions, 4/4 repaired per group (M6) | 4 synthetic problems; not a benchmark. |

Exit code `137` alone never establishes a cause. PyBox labels a termination
only when its own recorded KILL or the timer's timing supports it, and otherwise
says so.

## Documentation

| Read | For |
| --- | --- |
| [`site/`](site/index.html) | **The documentation site** (start here): install, first run, an 87-second walkthrough with captions, concepts, files, packages, CLI / Python / MCP guides, reference, performance, evidence, FAQ. Built from [`docs-site/`](docs-site/README.md) with `python3 docs-site/build.py`. |
| [Files in and out](site/files.html) · [Packages and longer runs](site/packages.html) · [MCP](site/mcp.html) | The M9 features. |
| [LEARNING.md](LEARNING.md) | The long-form lab notebook, milestone by milestone. |
| [Roadmap](docs/ROADMAP.md) · [Progress](docs/PROGRESS.md) | Accepted contract, release gates and status. |
| Results: [Step 4](docs/STEP4_RESULTS.md) · [M3b](docs/M3B_RESULTS.md) · [M3c](docs/M3C_RESULTS.md) · [M4](docs/M4_RESULTS.md) · [M5](docs/M5_RESULTS.md) · [M6](docs/M6_RESULTS.md) · [M8](docs/M8_RESULTS.md) · [M9](docs/M9_RESULTS.md) · [M10](docs/M10_RESULTS.md) | Dated real-runtime evidence and every preserved failure. |
| [M10 security review](docs/M10_SECURITY_REVIEW.md) | An independent adversarial review of the new surface, and how each finding was resolved. |
| [Evidence archive](docs/EVIDENCE_ARCHIVE.md) | How raw evidence is kept and verified (the evidence itself stays private). |
| [Final review](docs/M7_FINAL_REVIEW.md) · [M7 results](docs/M7_RESULTS.md) | Independent review findings and the M7 delivery record. |

## Status

M1–M6 are complete and locally qualified. M7 (documentation, site, review) is
delivered. M8 (installable, portable paths, `setup` / `vm` / `doctor`) is
implemented. M9 (the `data` image, files in and out, runs up to 30 s, `pybox exec`
with a readable receipt, configurable MCP, PyPI-ready packaging, benchmarks) is
implemented, unit-tested (198 tests) and checked live in a throwaway installation;
see [M9 results](docs/M9_RESULTS.md). M10 (matplotlib, your own images, final readings,
a 15× faster watcher, Cursor tests, an independent security review with every finding
resolved) is done; see [M10 results](docs/M10_RESULTS.md). Not done yet: a second Mac,
Claude Desktop, a PyPI release, the Homebrew tap. Committed locally on branch
`m9-useful-for-real-work`; not pushed.

## Contributing, security and changes

- [CONTRIBUTING.md](CONTRIBUTING.md): set up, run the tests, test against a real VM safely.
- [SECURITY.md](SECURITY.md): report a vulnerability privately; what's in scope.
- [CHANGELOG.md](CHANGELOG.md): what's in each release.

## License

[Apache License 2.0](LICENSE).
