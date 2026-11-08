# Changes

## 2.2.9 — 2026-11-08

- Check source-folder directory syncing before staging filenames, preserving originals and prior Undo when the filesystem rejects syncing.
- Persist the recovery log and newly created data-folder hierarchy before moving any source. Preserve prior Undo if recovery preparation fails.
- Add genuine synthetic FLAC metadata and content-preservation checks to source and packaged Rename/Undo workflows; require their evidence in release receipts.
- Reject recovery snapshots larger than the reader supports before changing filenames; keep recoverable state when a later checkpoint exceeds the limit.
- Recover valid interrupted 2.2.8 batches whose replay exceeds the snapshot limit by keeping durable status events in the existing log.
- Warn in the preview, status and tooltips before a filename will be hidden on Linux; keep intentional renames available.
- Verify real FLAC albums through cancellation, destination conflicts and abrupt process exits at each staging/final move.

## 2.2.8 — 2026-11-04

- Improve automatic Linux appearance matching with independent font, light/dark and accent providers, including desktop portals, KDE, explicitly selected qt6ct and a bundled native GTK reader. Basic matching needs no installed Python or PyGObject.
- Add saved system/custom font and accent controls, Refresh system settings and an appearance-only Reset. Appearance choices apply to all app text and Qt file/color dialogs.
- Let Rename move horizontally to its neighboring controls before the window reaches its measured minimum width. Remove the redundant border around Rules and reduce empty footer space.
- Open saved presets in a fitted Load dialog. Present rule booleans and exclusive options as accent-highlighted buttons while retaining their checkbox/radio keyboard and saved-value behavior.
- Fit ordinary forms to their active controls. Text-heavy rule editors allow horizontal resizing and remember a separate preferred width for each editor across mode changes and restarts. Long category lists and content still scroll; smaller screens clamp the visible width without replacing the preference.

## 2.1.0 — 2026-11-03

All interface text follows the configured desktop UI size, including headings, Help, tables and status. Document pages, exported captions and watermarks retain their own content typography.

Primary actions, enabled toggles, selections and progress use the system accent, with readable contrasting text. Secondary actions stay neutral. Desktop settings helpers use the host library environment, including in portable packages.

Compact controls preserve more vertical working space. File Renamer keeps its rule controls, Rename and Undo together: Rename shifts horizontally when needed, and resizing stops before the row collides. Layouts adapt to enlarged fonts and constrained monitor work areas.

## 2.0.12 — 2026-11-03

- Restore a useful minimum window size so the preview, everyday controls, task actions and status remain visible together.
- Measure the layout at the system font size; adapt the minimum to the current monitor and use scrolling when its work area is genuinely too small.
- Repair undersized restored windows while keeping the system-font improvements.

## 2.0.9

- Follow the operating system's interface font and text size, including Cinnamon,
  GNOME and MATE settings in Linux packages. Reopen the app after changing desktop
  font settings. Changing the app's appearance no longer resets the font.
- Keep rule editors, tables and status text at the system size. Reflow commands
  and scroll rule forms when larger text needs more room.
- Grow the file table's State column with larger desktop text so its header and
  On/Off controls remain complete, including when restoring older column widths.
- Treat straight and curly apostrophes inside words as part of the word in Case
  title mode: `It's` stays `It's`, and `DON’T` becomes `Don’t`. Preserve forced
  fragments, extension options and saved legacy preset behavior.
- Verify apostrophe handling through the packaged Case editor, preview, Rename
  and Undo workflow, including original filename and content restoration.

## 2.0.7

- Remove the affiliation statement from the README and Help dialog.
- Renaming behavior and saved preset formats are unchanged.

## 2.0.6

- State File Renamer's independence in the README and Help dialog.
- Package an explicit set of public documentation, remove stale staged docs, and
  fail builds with missing required files or linked documentation paths.
- Include a `LICENSE` alias so the packaged README's MIT license link works,
  retaining `LICENSE.txt`, third-party notices and dependency license texts.

## 2.0.5

- Clarify rule behavior, preset formats, platform limits and validation messages.
- Fix a startup crash when another File Renamer instance already holds the data
  folder lock. The second instance now shows the existing notice and exits after
  acknowledgement, preserving the first instance and its rename history.
- Reflow rule controls above Rename and Undo on narrow desktops, and fit restored
  windows to the available work area so acquisition controls and status stay visible.
- Preserve the build lockfile and source provenance in the isolated WSL builder.

## 2.0.4

- Fix adding a new rule: the editor now starts with a valid filename target instead
  of rejecting the rule with "Rule type and target must be text". Existing rule
  targets and saved preset formats are preserved.
- Exercise creation, editing, preset reload and filename results for all 19 rule
  choices through the editor controls, including native regex and Pascal rules.
- Make packaged checks create and edit rules through the actual Add Rule dialog
  before verifying preview, Rename and Undo with preserved source hashes.
- Add `--qa-ui FRESH_DIRECTORY` for isolated interactive checks without using
  ordinary application settings, presets or undo history.
- Require Ubuntu 24.04 checks of the exact retained Linux packages, including
  editor creation, Rename and Undo, before release readiness can pass.
- Omit the unused Qt TIFF decoder from Linux packages before dependency analysis;
  TIFF metadata still uses ExifTool. Packaged checks exercise real TIFF metadata
  and verify a TIFF file survives Rename and Undo unchanged.

## 2.0.3

- Improve contrast for the primary Rename action, selected rows, On buttons and
  progress text while keeping the established Studio layout.
- Verify the packaged application's actual preview, rename and Undo workflow on
  synthetic files, including restoration of original names and file hashes.
- Isolate Windows package builds from unrelated tools on the host DLL search path.
- Allow exact-commit draft restaging while invalidating stale readiness evidence.
- Make diagnostic destinations exclusive and preserve useful failure messages.
- Add explicit manual release staging with reviewed-commit/version guards,
  paginated release checks, and retained packaged workflow evidence.
- Put everyday examples and the correct application downloads first in the README.
