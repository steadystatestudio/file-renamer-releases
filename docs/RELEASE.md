# Releasing File Renamer 2.0.12

Release packages are built from an explicitly selected source commit on main.

The same release gates support `steadystatestudio/file-renamer-builds`, which remains
private, and the public release repository `steadystatestudio/file-renamer-releases`.
Release build logs are retained in the private build repository. Public release assets provide checksums, build information,
platform receipts, synthetic QA evidence and matching dependency sources.
The identical reviewed source commit and verified assets are published in the release
repository. Package metadata uses that public repository identity.

After reviewed changes are merged to main, manually dispatch **Release preparation**
in `build-release.yml` with the exact 40-character main commit and
`v2.0.12`. The script rejects an automatic push, another branch or unlisted repository, a
reviewed-commit mismatch, a tag/version mismatch, an existing moved tag, or any
published release. The full paginated release inventory is inspected before a
draft is created. The workflow never publishes or changes repository visibility.

A new dispatch may restage the same exact commit into its existing unpublished
draft. Before replacing any assets, staging removes `RELEASE-READY.json`;
finalization recreates it only after all receipts and digests pass for the new run.
A different commit requires a new version/tag; an existing tag is never moved.
Workflows for the same release tag are serialized.

Both Windows Server 2022 and Ubuntu 22.04 must pass the full source suite, build
native packages, and run the actual packaged preview helpers and GUI rename/Undo
workflow. The diagnostic creates and edits rules through the Add Rule/Edit dialogs,
then creates three synthetic files in a fresh folder, checks
the preview, renames through the real UI, undoes the batch, and verifies original
names and SHA-256 hashes. It refuses an existing destination. Native smoke reports
and screenshots are retained without synthetic input files or local settings.
The inputs include a real TIFF. Packaged preview and GUI checks require its
dimensions/model metadata and verify its content survives Rename and Undo.

Ubuntu 24.04 then downloads the retained Ubuntu 22.04 portable bundle and AppImage.
It verifies their exact receipt, source identity and hashes before running the same
editor/preview/rename/Undo checks on the bundle, AppImage and X11/Xvfb AppImage.
No application dependencies are installed into the verification host's Python.
`RELEASE-Ubuntu24.json` records the tested Linux receipt hash; finalization rejects
missing compatibility evidence or a subsequently replaced Linux build. It does
not rebuild the packages on Ubuntu 24.04.

The draft includes package checksums, source commit/tree metadata, passing tests,
matching dependency sources and native library notices. Finalization verifies
all retained asset digests before creating `RELEASE-READY.json`.

Native builds stage the explicit public documentation list in
`scripts/package_documentation.py`, replacing any previous packaged docs directory.
Missing required files stop the build; linked documentation paths are rejected.
The full MIT license is included as both `LICENSE` (for README's local link) and
`LICENSE.txt`, alongside third-party notices and dependency license texts.
Build checks and native portable-bundle smoke checks verify the staged documents
against source. Inspect the same documentation inside the final AppImage before publication.

Before publishing the stable release, inspect that receipt and exact bytes,
validate the user-facing screenshots and exercise ordinary dialogs on the
candidate. Keep unsigned-package instructions and actual platform limitations
visible. Publish the verified bytes without changing their source tag. This
workflow claims Ubuntu 24.04 compatibility only when its retained-package job has
passed for those exact bytes. It does not certify physical desktop hardware,
Wayland, accessibility or every filesystem.

For an interactive check, launch `File-Renamer.exe --qa-ui FRESH_DIRECTORY` on
Windows (use the platform executable on Linux). The directory must not exist.
The path and its ancestors must not be symbolic links or Windows junctions.
This opens the ordinary empty interface with settings, presets and history confined
to that directory, and performs no automatic actions. Select only synthetic test
copies: the normal Rename and Undo actions still act on files you explicitly add.
This is distinct from the automated `--smoke-workflow` mode.
