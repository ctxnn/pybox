# M8 plan — make PyBox installable and portable beyond one Mac

Drafted and **approved by the owner** on 20 October 2026 (historical docs: normalize
paths). Implemented; see [M8_RESULTS.md](M8_RESULTS.md).

## Goal

Another person on an Apple Silicon Mac can install PyBox, run one guided setup,
and safely run code in the restricted engine. The same safety guards apply as on
the qualified machine, with no new silent behaviour. The owner's existing
runtime must keep working unchanged, including its retained sentinels.

## Why it is single-machine today

| Hard-coded today (`pybox/container.py`) | What it really is |
| --- | --- |
| `HOME = Path("/Users/<owner>")`, `USER`/`LOGNAME` | The current user's home and name |
| `ROOT = HOME/.pybox/runtime` and sub-paths | A per-user private runtime root |
| `CONTEXT = …/contexts/meta/3c51b707…/meta.json` | Docker's own layout: the directory is `sha256("colima-pybox")` |
| `/opt/homebrew/bin/docker`, `/opt/homebrew/bin/colima` | The Homebrew default on Apple Silicon |
| VM profile `pybox`, image `python@sha256:70729b46…` linux/arm64 | Fixed by design; keep |

The runtime itself was created by hand on 18 October (private directories, an
anonymous Docker config, the no-port-forward Lima override, one `colima start`
with fixed flags, one pinned image pull). Nothing in the repository recreates it.

## Design

### 1. Derive identity and paths; keep every guard

- `HOME = Path.home()`, user from `pwd.getpwuid(os.getuid())`. All existing checks
  stay: canonical, non-symlink, owned by the caller, mode `0700` directories and
  non-group/other-writable files, exact override/config/context contents, socket
  type and ownership.
- `CONTEXT` is computed as `contexts/meta/<sha256("colima-pybox")>/meta.json`.
- Tools are found only in a fixed allowlist, `/opt/homebrew/bin` then
  `/usr/local/bin`. The resolved binary must not be group- or world-writable. There
  is no `$PATH` search and no ambient `DOCKER_HOST`/`DOCKER_CONTEXT` (the child
  environment stays the fixed `ENV`).
- Supported platform: macOS on arm64 (Colima `vz`, aarch64). Anything else fails
  closed with a clear message. Linux and Intel are out of scope.
- For the owner these resolve to exactly today's values. A unit test pins that
  equivalence, so the qualified behaviour does not drift.

### 2. `pybox setup` — consent-gated, idempotent, dry-run by default

`pybox setup` prints a plan and changes nothing. `pybox setup --yes` executes it:

1. Check prerequisites: `colima` and `docker` present in the allowlist. If not,
   print `brew install colima docker` and stop. **PyBox never installs software.**
2. Create the private runtime tree (`0700`), the anonymous `docker/config.json`
   (`0600`) and the Lima no-port-forward `override.yaml` (`0600`), using exclusive
   creation. An existing file must match byte-for-byte or setup stops; it never
   overwrites.
3. Start the dedicated profile once with the same fixed flags as the qualified
   runtime (`--mount=none --port-forwarder=none --activate=false
   --ssh-config=false --ssh-agent=false --kubernetes=false` …). **This downloads
   Colima's VM image (~330 MB) on first run.** The plan says so before asking.
4. Pull **only** the pinned digest for linux/arm64 (registry contact; Docker
   reports the size),
   then verify RepoDigest, image ID and platform.
5. Verify the guard, then stop the VM. Report what was created and its size.

If the runtime already exists and verifies (the owner's machine), setup reports
"already set up" and does nothing.

### 3. `pybox vm start | stop | status`

Users need a supported way to run the VM. `start` runs the same fixed command,
then reads back the profile config (no mounts, no port forwarder, no network
address) and the guard before reporting ready. `stop` and `status` are thin
wrappers. Other `pybox` commands still never start the VM implicitly. The
whole-Mac listener comparison remains a **qualification** gate in `tools/`, not
part of everyday start; the docs say so explicitly.

### 4. `pybox doctor`

A read-only report: platform, tools, runtime tree, guard result, VM state,
whether the pinned image is cached (only when running), and pending attempts.
It touches no containers.

### 5. Packaging

- `pyproject.toml`: stdlib only, `requires-python >= 3.11`, a `pybox` console
  script, and package data (`_observe.sh`). Install with
  `pip install git+https://github.com/ctxnn/pybox` once published, or
  `pip install -e .` from a clone.
- MCP clients use `pybox mcp` (or `python -m pybox mcp`). Generic config
  examples only; no GUI/SDK interop claimed until tested.
- `tools/serve_mcp.py` stays for running from a checkout.

### 6. Personal data

- Code, tools and examples: replace literal home paths with `Path.home()` or
  repo-relative paths (`tools/runtime_validation.py`, `tools/validate_step4.py`,
  `tools/audit_secrets.py`). The owner's qualification behaviour is unchanged.
- Historical docs (results, LEARNING, ledger, handoff, checkpoint review, README
  snapshot) contain `/Users/<owner>/…` text. **Owner decision needed:**
  (a) normalize those paths to `~/…` and repo-relative text, leaving evidence
  files untouched (the ledger's numbers and outcomes don't change, only path
  spellings); or (b) keep them as-is and exclude the historical docs from the
  public tree.

### 7. Qualification

- Unit tests: derived paths with a fake home; owner-equivalence pin; the context
  hash; the tool allowlist (rejects writable/missing binaries); setup dry-run and
  idempotence against a temporary home (Colima/Docker faked); refusal to
  overwrite; doctor read-only.
- **No live run in this session.** The owner's VM and sentinels are not touched.
- Real qualification needs a second Mac or a second macOS user account: run
  `pybox setup --yes`, the `tools/` gates, then the offline + live quickstart.
  That is an owner step, recorded as M8 results.

## Out of scope

Linux/Intel hosts, Docker Desktop, auto-starting the VM from MCP, any public
execution service, PyPI publication, and changing the restricted policy.

## Deliverables

Code changes in `pybox/container.py`, new `pybox/runtime_setup.py` (setup / vm /
doctor), CLI wiring in `pybox/__main__.py`, `pyproject.toml`, tests, and updates
to README, REFERENCE and the site (status: "install from source; restricted
engine after `pybox setup`"). All uncommitted for review.
