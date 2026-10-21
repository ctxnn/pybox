# Contributing to PyBox

Thanks for helping. PyBox's value is that every claim it makes is checked, so changes are
held to the same standard: tested, measured where it matters, and described honestly.

## Set up

You need an Apple Silicon Mac, Python 3.11 or newer, and `brew install colima docker`.

```bash
git clone https://github.com/ctxnn/pybox && cd pybox
python3 -m pip install -e .
```

(Users install the released package with `pipx install pybox-sandbox`.)

PyBox has no Python dependencies. Keep it that way: the engine uses only the standard
library.

## Run the tests

```bash
python3 -B -W error::ResourceWarning -m unittest discover -s tests
```

The tests mock the container engine, so they don't need the VM and never start it. They
must all pass, and new behaviour needs new tests. A security-relevant change needs a test
that shows the attack failing.

## Test against a real VM without touching your own setup

Use a separate installation, so your own runtime and its leftovers are never involved:

```bash
mkdir -m 700 ~/.pybox-qa
HOME=~/.pybox-qa pybox setup --yes --with data
HOME=~/.pybox-qa pybox vm start
HOME=~/.pybox-qa pybox exec - <<< 'print(6*7)'
HOME=~/.pybox-qa python tools/bench.py --runs 10
```

Afterwards, stop it and remove it completely:

```bash
HOME=~/.pybox-qa pybox vm stop
HOME=~/.pybox-qa COLIMA_HOME=~/.pybox-qa/.pybox/runtime/colima LIMA_HOME=~/.pybox-qa/.pybox/runtime/colima/_lima colima delete --force pybox
rm -rf ~/.pybox-qa
```

## Rules for changes

- **The default box is qualified evidence.** `_create_args` and `_check_policy` for the
  default `stdlib` run, and the box's first process, are pinned by a test. Changing them
  means re-running the restriction and resource checks and recording the results.
- **Fail closed.** If PyBox can't establish something, it says so (`UNKNOWN`,
  `UNCONFIRMED`) instead of guessing, and it refuses to run rather than run unsealed.
- **Everything from the box is untrusted:** stdout, stderr, returned files and their
  names. Escape and bound it before it is printed, encoded or written.
- **No new commands, paths or options from callers** reach `docker`, `colima` or `ssh`.
  Only validated, fixed values do.
- **`pybox/runner.py` and its tests are frozen.** The unsafe native runner is a learning
  tool; don't extend it. Bug fixes go in with their own tests in a separate file (see
  `tests/test_runner_zombies.py`).

## Docs

Pages live in `docs-site/pages/`; build with `python3 docs-site/build.py` and open
`site/index.html`. Every number on the site must match the source or a dated, recorded
run, and a recorded run is labelled as one. Plain language first, the exact setting
second. See [docs-site/README.md](docs-site/README.md).

## Pull requests

Describe what changed and why, how you tested it (unit tests, and live runs if any), and
anything the docs or the receipt now say differently. For security issues, please don't
open a pull request or issue. Follow [SECURITY.md](SECURITY.md) instead.
