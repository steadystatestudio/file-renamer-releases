# Recovery and preview validation

## Version 2.2.9

This release strengthens interrupted-rename recovery and preview warnings.

The update checks source-folder syncing before moving files, makes recovery state durable before staging names, and preserves previous Undo history when preparation fails. Recovery also handles valid older snapshots whose replayed log is larger than the snapshot limit. Names beginning with a dot receive a visible warning because Linux file managers normally hide them; intentional renames remain available.

## Synthetic coverage

Tests use generated files and isolated settings. Media coverage includes a valid synthetic FLAC with artificial Title and Artist tags.

Checks cover ordinary Rename and Undo, restart recovery, cancellation, destination conflicts, abrupt process exit at each staging/final move, directory-sync rejection, and near-limit legacy recovery. Complete-file hashes are compared before and after operations. The packaged GUI workflow creates and edits rules, previews four synthetic files, renames them, undoes the batch, and verifies names and hashes.

The official release gates require Windows and Ubuntu source/build checks, exact frozen-package checks, Ubuntu 24.04 verification of retained Linux packages, matching source/dependency receipts, and artifact digests. See the exact release's notes and receipts for completed results; earlier candidate checks do not certify rebuilt bytes.

## Limits

Automated process-exit and injected-I/O tests do not establish physical power-loss safety, every filesystem or hardware configuration, or universal recovery guarantees. See release notes for completed desktop checks. Keep backups of important files. External edits, missing storage and conflicting filenames can prevent recovery.
