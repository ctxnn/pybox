# Security policy

PyBox runs Python you don't trust, so a weakness in it matters. Thank you for looking.

## Reporting a vulnerability

Please report privately, not in a public issue:
**[Report a vulnerability](https://github.com/ctxnn/pybox/security/advisories/new)**
(GitHub's private vulnerability reporting).

Include what you need for someone else to reproduce it: the PyBox version
(`pybox --version`), macOS version, the program or MCP request that triggers it, what you
expected, and what happened. A failing unit test or a short program is ideal.

You can expect an acknowledgement within a week. Fixes are released as soon as they are
ready, with credit in the [changelog](CHANGELOG.md) unless you'd rather not be named.
Please give a reasonable time to fix before disclosing publicly.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.3.x | Yes |
| Earlier | No (never released) |

## What counts as a vulnerability

PyBox's promises are listed in the [README](README.md#what-pybox-promises--and-what-it-does-not)
and the [evidence page](https://ctxnn.github.io/pybox/evidence.html). A report is in scope
when a program run with `pybox exec` or `run_container`, or an MCP client calling
`run_python`, can do something those promises rule out. For example:

- read or write files on the Mac, or reach the network, from inside the box;
- make PyBox write outside the chosen `--output` folder, overwrite a file, or follow a link;
- get past the limits: memory, processes, CPU, time, file sizes, or the MCP server's
  `--max-timeout` and `--images`;
- make the receipt claim something false in its trusted sections (container engine and
  Linux kernel), or hide that cleanup failed;
- get a package installed during an image build that the lock file didn't pin;
- run commands on the Mac through PyBox's calls to `docker`, `colima` or `ssh`.

## Out of scope

- Anything that needs the Mac user's own account already compromised, such as writing to
  `~/.pybox/runtime` or replacing `docker` or `colima`.
- `pybox run --unsafe-local`, which is explicitly **not** sandboxed.
- Content of program output or returned files. These are untrusted by design, and the
  receipt labels them so. That includes text aimed at an AI model reading them.
- Weaknesses in Docker, Colima, Lima, the Linux kernel or macOS themselves. Please report
  those upstream (we're glad to hear about them too).
- Denial of service against your own Mac by a program you chose to run with high limits.

PyBox is a research prototype that has been tested, not certified. Please don't rely on it
alone for hostile code from the public internet.
