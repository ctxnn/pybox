# Durable evidence archive

Archived on 19 October 2026 at 18:07 UTC, before any checkpoint commits.
Root: `evidence/`.
The entire directory is excluded by the repository's `/evidence/` ignore rule.

## Copy and verification

Every top-level `pybox-*` item found in `/private/tmp` was copied, including
directories, standalone manifests, summaries, scripts and test/console logs:

| Measure | Verified result |
| --- | --- |
| Top-level items | 89 |
| Regular files | 2,481 |
| Total file bytes | 15,949,608 |
| Original SHA-256 preservation manifests | 16 |
| Entries verified against those original manifests | 2,386 |
| Symlinks or special files in the source inventory | 0 |

Each copied file's SHA-256 matched the source; the source's size, modification
time and hash were checked again during copying. The original temp artifacts
were left untouched. Raw copies have mode 0400 and directories 0500 under a
private evidence root. These permissions discourage accidental changes; SHA
verification is the integrity check. This is a durable local copy, not a remote
backup or a Git-hosted artifact.

The independent verifier reads only the durable archive and its manifests:

```sh
cd /path/to/pybox
/usr/local/bin/python -B tools/verify_evidence_archive.py
```

It verifies all 2,481 copied files and rechecks all 2,386 original manifest
entries without relying on the temp originals. A successful result has
`passed: true`.

## Index and historical references

- [Raw byte-preserved artifacts](../evidence/raw).
- [Copy inventory and original metadata](../evidence/archive-report.json).
- [Relative SHA-256 manifest for every copied file](../evidence/raw-sha256.json).
- [Historical path map](../evidence/path-map.json).
- [Repository reference changes](../evidence/reference-updates.json).
- [Shared-document reference changes](../evidence/external-reference-updates.json).
- [Original documents before relocation](../evidence/reference-update-backup).

Active repository documentation, both shared roadmap/resource documents and the
two validation-tool evidence inputs now reference the durable copies. Guest
scratch and observer-marker paths were left intact. Historical raw JSON,
manifests, logs, source snapshots and document backups retain their original
embedded paths so that their bytes still match the original hashes. Resolve
those historical paths using the longest matching prefix in `path-map.json`.
This includes both `/private/tmp/` and its macOS `/tmp/` alias. Old statements
about temporary evidence storage describe storage at the time of a milestone;
the copies are now here.

## Credential audit

[The machine-readable audit](../evidence/secret-scan-report.json)
covers current repository files (including ignored evidence and Git metadata),
the original PyBox temp artifacts, historical PyBox worktrees, PyBox runtime log
files, and every stored Git blob/commit/tag object, including unreachable objects.
It checks provider prefixes, literal credential assignments, bearer tokens,
private-key headers, JSON-escaped variants and standard base64 encodings.
Positive controls run only in memory. Matched credential values are never
written to the report.

No credential patterns were detected in the scanned project files, evidence,
test/runtime logs or stored Git objects. The report records file/object counts,
read errors and skipped symlinks. This is a pattern scan, not proof against
arbitrary unknown or obfuscated secrets.

**Exception outside the project:** the Codex session log for this conversation
contains the NVIDIA API key pasted by the user. That log is outside the repo,
was checked separately, and was neither copied nor modified. Therefore an
unqualified claim that no API key exists in any local log would be false.
The existing key should be revoked through the provider. The report records
only finding metadata and the external log's path, never the key itself.

## Checkpoint review

[Checkpoint review](CHECKPOINT_REVIEW.md)
groups the uncommitted Step 4 through M6 changes. Review snapshots, text patches
and fresh offline test logs are stored in
`evidence/review/`.
The archive operation does not run the VM, call a provider, or authorize commits.
