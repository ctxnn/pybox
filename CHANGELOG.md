# Changelog

All notable changes to PyBox. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-10-22

The first public release, on PyPI as `pybox-sandbox` (the command and import are `pybox`).
PyBox runs a Python program once in a fresh, sealed Linux
container inside a private VM on an Apple Silicon Mac, and returns a receipt that keeps
what was configured, what the engine and kernel observed, what the program said, and
what is unknown apart.

### Added

- **Sealed runs.** `pybox exec FILE` (or `-` for standard input) runs a program in a
  brand-new box: no network, no Mac folders, read-only system, non-root user with every
  capability dropped, 128 MiB, 32 processes, half a CPU, a 2-second default limit. The
  settings are read back from the engine and checked before the program starts.
- **A readable receipt** in the terminal, grouped by source (container engine, Linux
  kernel, the program, not known); `--json` prints the full versioned record.
- **Two deadlines.** PyBox's own limit, plus a kill timer that runs as the box's first
  process, so a program can't outlive PyBox even if PyBox is killed.
- **Crash-safe cleanup.** A note is written before every box is built; the next run or
  `pybox cleanup` removes only this installation's expired, stopped leftovers.
- **Kernel counters** (memory, processes, CPU) read from outside the box while it runs,
  with a brief final reading on opt-in runs.
- **Images with packages.** `pybox setup --yes --with data` builds an image with numpy,
  pandas and matplotlib; `pybox image build NAME --lock FILE` builds one from your own
  lock file of exact pins with hashes. Each is checked by image ID and recipe hash before
  every run.
- **Longer runs** up to 30 seconds with `--timeout`.
- **Files in and out.** `--input` copies files or folders in (64 files, 8 MiB);
  `--output` brings back what the program writes, all at once, never overwriting or
  following links, marked with `com.apple.quarantine`.
- **MCP server for AI agents.** `pybox mcp` offers one tool, `run_python`, with optional
  images, files and returned files. The person configuring the server sets
  `--max-timeout` and `--images`; agents can only ask for less. Tested with Claude Code
  and Cursor's command-line agent.
- **AI repair loop** in which a model may only propose full source, within reserved
  request, token, byte and time budgets.
- **Consent-gated setup.** `pybox setup` shows its plan before changing anything;
  `pybox vm start | stop | status`; a read-only `pybox doctor` that says what to do next.
- **Python API:** `run_container` and `cleanup_containers`.
- **Documentation site** with an 87-second captioned walkthrough, built from `docs-site/`.
- `tools/bench.py`: a complete fresh-box run takes about 0.2 s once the VM is running.

### Fixed

- The native learning runner no longer reports `process-group check failed: Operation not
  permitted` after a timeout. macOS answers `EPERM` while a process group holds only
  unreaped zombies; the runner now keeps checking and reports it only if the group
  outlasts the cleanup deadline.

### Security

- An independent adversarial review of the files, images, MCP and watcher code found
  2 medium, 6 low and 6 informational issues. All were fixed or documented before this
  release; see [docs/M10_SECURITY_REVIEW.md](docs/M10_SECURITY_REVIEW.md).

### Known limits

- macOS on Apple Silicon only; set up and tested on one machine.
- Not yet tested with Claude Desktop or the official MCP SDKs.
- Not certified for hostile code from the public internet. See [SECURITY.md](SECURITY.md).

[0.3.0]: https://github.com/ctxnn/pybox/releases/tag/v0.3.0
