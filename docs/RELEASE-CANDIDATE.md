# File Renamer 2.0.2 release preparation

This is a candidate, not evidence that a public release already exists.

- Preserves the established drag/drop, ordered rules, preview, Rename and Undo
  workflow. No redesign and no new account, upload or telemetry behavior.
- ExifTool previews explicitly disable external `.ExifTool_config` files, so a
  personal Perl configuration cannot execute as a side effect of metadata preview.
- All existing rename, collision, restart recovery and undo checks run on both
  native CI platforms. Packaged startup and real preview-worker checks run on
  Windows and Linux, plus Linux X11/Xvfb.
- Locked dependencies retain Qt 6.11.0. Packages carry license inventories,
  replacement instructions and matching source-archive pins.
- `release-candidate.yml` retains successful packages, checksums, synthetic QA,
  and clean source in a **private draft**, bypassing Actions artifact storage.
  It never publishes. `RELEASE-READY.json` only certifies the automated gates.

Public distribution must use an audited clean source snapshot in
`steadystatestudio/file-renamer-releases`, not expose the private development
history. Keep matching library source archives available beside the binaries.
Review the exact retained package inventory and checksums before publication.
Windows binaries are unsigned: follow normal security policy; do not disable
protection. Automated offscreen checks do not certify interactive Windows 10/11,
high-DPI hardware, accessibility, or every Linux desktop/filesystem.

Start with copied sample files. Renaming changes filenames on disk; the most
recent batch is undoable only while its files and journal remain intact. Existing
external changes or occupied original filenames can require manual resolution.
