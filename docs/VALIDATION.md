# Current-release evidence

The sections below are historical development measurements, not a certification
of every later package. For the exact downloadable release, use its release notes,
`BUILD-INFO-*.json`, `RELEASE-*.json`, and SHA-256 checksum files. The candidate
workflow runs fresh native tests and packaged GUI/preview-worker checks on Windows
and Linux and remains draft-only until the retained bytes are reviewed.

Linux packages now leave distribution-owned shared libraries on the host and
include `LINUX-SYSTEM-DEPENDENCIES.json`; older descriptions of a fully bundled
system-library closure below describe the older package only. Automated headless
checks do not certify interactive Windows 10/11, physical high-DPI hardware,
Wayland, accessibility or every filesystem.

---

# Validation — 2026-09-19

## October 5 stable AppImage updates

- Linux now produces `dist/File-Renamer-x86_64.AppImage` and its matching SHA-256 file.
  Builds, WSL export, CI launch checks, and current usage instructions use the same name.
- Application identity and storage helpers retain the existing Qt user settings and
  data paths. A regression check verifies these paths stay unchanged across an
  executable filename change and an application version change; no migration is required.
- Windows: **299 passed, 3 skipped**. Linux/WSL: **293 passed, 9 skipped**.
  Ruff passed on both platforms.
- Windows portable ZIP and Linux AppImage rebuilt; both SHA-256 files verified.
  Packaged GUI and preview-worker checks passed on Windows, native Linux, and the
  AppImage, including Linux X11/Xvfb launch checks and source-file integrity.
- Internal app version remains 2.0.1. Linux verification uses Ubuntu 22.04 under WSL 2.

## October 5 Pass 10 interface update

- Rules, Rename, and Undo share a single row. Rename remains centered and Undo
  stays at the right edge; minimum width prevents control collisions.
- All 18 rule families use visible radio choices and compact checkboxes, with
  12-point text and inline position/delimiter fields. Existing rule and preset
  behavior is preserved, including legacy editors.
- Dialogs measure the current editor and reflow choices on narrow screens.
  Vertical scrolling is reserved for content exceeding available screen height.
- Windows full regression suite: **297 passed, 3 skipped**; GUI suite: **132 passed**.
  Ruff passed. Coverage includes all rule
  editor round trips, exclusive choices, retained inline values, short-screen
  reflow, toolbar placement, preview, rename, undo, and recovery.
- Linux/WSL native ext4 regression suite: **291 passed, 9 skipped**; Ruff passed.
- Windows portable ZIP and Linux AppImage rebuilt. Packaged GUI and preview
  worker checks passed, including native regex, Pascal, metadata, and unchanged
  source contents. Linux also passed AppImage and X11/Xvfb launch checks.
- Rendered all 18 editors in light/dark themes at standard and 150% scaling;
  inspected contact sheets and detailed Insert, Delete, Serialize, Case, Date,
  and Pascal editors. Main-window renders cover collapsed, narrow, and wide
  layouts. Validation uses Qt offscreen rendering.

## October 2, version 2.0 rule expansion

- Windows: **256 passed, 3 skipped**, plus **4 passed** for final option/date edge cases.
- Linux/WSL: **250 passed, 9 skipped**. Ruff passed on both platforms.
- All 18 ReNamer rule families have editors and executable transformations;
  old presets retain their original behavior. Editor defaults round-trip in GUI tests.
- Native regular expressions, genuine PascalScript execution, metadata extraction,
  per-preview script state, and frozen-package preview workers were exercised.
- Rendered all 18 editors in light and dark themes on both platforms; inspected
  final date and transliteration layouts. Configuration uses vertical scrolling
  without a horizontal scrollbar.
- Windows portable package and Linux AppImage were rebuilt with the native rule
  helper and ExifTool. Packaged GUI/worker checks include source-file integrity;
  Linux checks use offscreen Qt and X11.
- Reference alignment uses installed resources and official documentation.
  Exhaustive live comparison with ReNamer was unavailable. Metadata readers and
  independent transliteration examples have documented compatibility limits in
  [the comparison notes](RENAMER_COMPARISON.md).

## Earlier October 2 UI feedback validation (before rule expansion)

- Windows regression suite: **181 passed, 3 skipped**; GUI suite: **77 passed**.
- Ruff and `git diff --check` passed.
- Regression coverage includes preset identity across restart (modified and missing
  presets), active-first preset loading, mouse/keyboard highlight toggles, matching
  Save Preset typography, and fitting both rule areas without horizontal scrolling.
- Rendered light/dark, narrow/full/wide, rule editor, Settings, and Save Preset
  screenshots. Inspected standard and 150% display scaling through Qt offscreen.
- Existing transformations and preset formats are unchanged. ReNamer alignment
  used installed resource strings; live reference layout was not verified.
- This change was validated from source on Windows; distribution bundles and
  Linux validation have not been refreshed for this update.


## Preset and centered action update - 2026-09-21

- Windows: **172 passed, 3 skipped**. Linux/WSL: **166 passed, 9 skipped**.
- Ruff and `git diff --check` passed. Regression coverage includes centered actions,
  fixed Undo spacing, long preset names, modified preset identity, Save defaults,
  and deletion selection, cancellation, and storage errors.
- Inspected Windows light/dark layouts and 200% scaling, plus the Linux dark layout.
  The outer scroll area is removed; rule and file tables retain internal scrolling.
- Built the Windows portable ZIP and Linux x86-64 AppImage. Both packaged GUI and
  preview workers passed smoke checks; Linux also passed X11/Xvfb launch checks.
- Verified Windows ZIP integrity and both distribution SHA-256 checksums.
- Layout inspection used Qt offscreen rendering; Linux packaged launch additionally
  used X11/Xvfb. No physical desktop or multi-monitor interaction was tested.


## Interface feedback update

- The pre-update version was checkpointed and pushed as `abe181a` after **119 passed,
  3 skipped** on Windows and a successful Ruff check.
- Updated Windows suite: **135 passed, 3 skipped**. Linux/WSL: **131 passed, 7 skipped**.
  Skips cover platform-specific behavior and Windows symlink privileges.
- Ruff and `git diff --check` passed. Tests use isolated temporary files and settings.
- Added coverage for fixed action positions at narrow/normal/wide widths, centered
  Rename, maximize and geometry restoration, recovery of offscreen positions,
  column widths/visibility/reset, and double-click fitting beyond 1,000 rows.
- Rule tests cover list selection, keyboard navigation, definition fields, and
  existing-rule round trips. Preset selection remains keyboard accessible without
  the dropdown arrow; popup fonts are checked at 12 pt.
- Progress checks cover the two rename passes, file counts, rename/undo completion,
  failures, empty operations, indeterminate progress, and closing while busy.
- Rendered and inspected light/dark, collapsed, narrow, wide, rule-editor, and
  segmented-progress layouts. Windows renders were also checked at 200% scaling;
  the Linux documentation screenshot was regenerated with the Linux Qt runtime.
- Rebuilt the Windows portable ZIP and Linux x86-64 AppImage with this update.
  Both packaged GUIs and preview workers passed smoke checks. The AppImage also
  passed the X11/Xvfb launch check. Windows ZIP integrity and the exported Linux
  SHA-256 checksum were verified; both distributions have companion checksum files.
- GUI layout verification used Qt's offscreen platform, including Linux under WSL;
  packaged Linux launch was also checked under X11/Xvfb. No physical multi-monitor
  or desktop window-manager interaction was performed.

## Version 1.1 update

- Windows: **119 passed, 3 skipped** (symlink privilege and two Linux-only cases).
- Linux/WSL: **115 passed, 7 skipped** (Windows-only cases).
- Ruff passed. The suite includes 10,000-file preview, isolated regex timeout,
  rename/undo/recovery, editable TOML/JSON backups, new rules, native filename
  policy, Unicode length boundaries, filesystem limits, and layout persistence.
- Both portable packages passed GUI and worker smoke checks. Linux AppImage also
  passed the X11/Xvfb check with extraction mode.
- Updated dark/light and collapsed screenshots are generated by
  `scripts/render_preview.py`; the README screenshot shows the new Rules table.
- ReNamer 7.10.0.0 was downloaded and its resources inspected. Live comparison
  remains unverified because the Windows Computer Use native pipe was unavailable.
  See [comparison notes](RENAMER_COMPARISON.md).

## Original version 1.0 verification

The following stress timings and platform checks describe the earlier baseline;
the update's automated results are listed above.

### Verified on Windows

- Windows 11 x64, Python 3.12.10, PySide6 6.11.0.
- **68 automated tests passed; 1 skipped.** The skipped test needs Windows symlink creation privilege.
- Ruff checks and Python compilation passed.
- The portable Windows executable's actual GUI and isolated preview worker passed smoke tests.
- Portable ZIP contents include the executable, runtime, icon, documentation, and license texts.
- Light/dark interfaces were rendered and visually inspected with Qt display scaling at 100% and 200%.
  Small logical screens keep controls reachable through the outer scroll area.

Automated cases cover rule ordering, literal and regex replacement, Unicode, protected extensions,
numbering order, preset round trips, real checkbox clicks, drag-and-drop, stale previews, GUI rename
and undo, collision rejection, missing/modified sources, simulated permission failures, cancellation,
undo conflicts, journal write failures, torn log records, and recovery from each of the six moves
in a three-file rename cycle. A pathological regex was terminated while the GUI continued responding.

### 10,000-file stress check

`python scripts/benchmark.py` created an isolated batch with distinct file contents, previewed it,
renamed every file, verified contents, undid the batch, and verified all original names and contents.
No temporary rename files remained. The test directory was removed afterward.

| Phase | Measured time |
|---|---:|
| Collect 10,000 files | 1.70 seconds |
| Generate and validate preview | 1.66 seconds |
| Commit rename | 150.02 seconds |
| Verify renamed contents and undo | 172.69 seconds |

These are measurements in this Windows workspace, not performance guarantees. Per-move durable
journaling prioritizes recoverability and makes large commits/undo operations substantially slower
than preview. The application displays progress and runs these operations outside the GUI thread.

### Verified on Linux

- Ubuntu 22.04.5 x86-64 under WSL 2, glibc 2.35, Python 3.12.14, PySide6 6.11.0, PyInstaller 6.22.2.
- **63 automated tests passed; 6 Windows-only naming-policy tests skipped.** This includes native
  Linux no-replace renames, symlinks, rollback/recovery, and the 10,000-file preview.
- All **17 GUI tests** also passed under X11/Xvfb (a second run of the GUI subset).
- The native Linux bundle and final AppImage passed packaged GUI and preview-worker smoke checks.
- AppImage launch was verified both through FUSE and with `APPIMAGE_EXTRACT_AND_RUN=1`.
- The AppImage GUI was additionally launched with the X11 `xcb` backend under Xvfb.
- Linux light/dark screenshots were rendered and visually inspected. The X11 checks identified
  a missing `libxcb-shape0` dependency; it is now installed and included in the packaged library closure.
- The deliverable is `dist/File-Renamer-x86_64.AppImage`, with a companion SHA-256 checksum file.
  Rebuild instructions are in [LINUX_BUILD.md](LINUX_BUILD.md).

## Verification limits

Linux verification used Ubuntu 22.04 under WSL 2 and Xvfb, not a separate physical Linux desktop.
Wayland and other distributions have not been exercised. GitHub Actions definitions are updated
to use the same dependencies and packaging checks, but no remote workflow was run in this session.

The tests exercise process interruption and simulated I/O errors, not physical power loss or
every network filesystem. A batch consists of individually journaled moves, not one atomic
filesystem transaction. Unresolved external changes can require recovery.
