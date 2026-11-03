# Changes

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
