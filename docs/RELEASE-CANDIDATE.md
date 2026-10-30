# Releasing File Renamer 2.0.3

The public `file-renamer-releases` repository contains the current source. Preserve
the older private repository and its history; do not reset or mirror it.

After reviewed changes are merged to main, manually dispatch **Stage reviewed
release candidate (draft only)** with the exact 40-character main commit and
`v2.0.3`. The script rejects an automatic push, another branch/repository, a
reviewed-commit mismatch, a tag/version mismatch, an existing moved tag, or any
published release. The full paginated release inventory is inspected before a
draft is created. Staging never publishes or changes repository visibility.

A new dispatch may restage the same exact commit into its existing unpublished
draft. Before replacing any assets, staging removes `RELEASE-READY.json`;
finalization recreates it only after all receipts and digests pass for the new run.
A different commit requires a new version/tag; an existing tag is never moved.
Workflows for the same release tag are serialized.

Both Windows Server 2022 and Ubuntu 22.04 must pass the full source suite, build
native packages, and run the actual packaged preview helpers and GUI rename/Undo
workflow. The diagnostic creates three synthetic files in a fresh folder, checks
the preview, renames through the real UI, undoes the batch, and verifies original
names and SHA-256 hashes. It refuses an existing destination. Native smoke reports
and screenshots are retained without synthetic input files or local settings.

The draft includes package checksums, source commit/tree metadata, passing tests,
matching dependency sources and native library notices. Finalization verifies
all retained asset digests before creating `RELEASE-READY.json`.

Before publishing the stable release, inspect that receipt and exact bytes,
validate the user-facing screenshots and exercise ordinary dialogs on the
candidate. Keep unsigned-package instructions and actual platform limitations
visible. Publish the verified bytes without changing their source tag. This
workflow does not claim Ubuntu 24.04 compatibility or human accessibility testing.
