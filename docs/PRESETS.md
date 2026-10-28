# Import and export rule presets

Open **Preset** at the right end of the Rules control row. **Load** lists saved presets.
The current preset name appears at the top center; editing its rules marks it as modified.
**Save...** starts with the current preset name, so clicking OK updates that preset.
For rules without a saved preset, enter a name. **Delete...** opens a list where you
can select one saved preset and click Delete, or Cancel. Deleting a preset keeps
the current rules in the editor.

Use **Export...** to save the current rules to a file you choose. TOML is the default;
JSON remains available. **Import...** accepts both formats, including older version-1
JSON backups. Import loads the rules and adds a named preset; an existing name gets
a numbered suffix rather than being replaced.

Backups include rule order, enabled state, target, and options. They contain no
files or rename history. Unsaved changes are included. Internal presets and undo
journals remain in the application's user data directory.

New exports use version 2 and include `behavior = "legacy"` or
`behavior = "renamer"` per rule. Version-1 imports remain legacy, preserving their
options and conventions. New rules use one-based positions and `skip_extension`;
legacy rules retain `target`. Both behaviors can appear in one preset. The
version-1 examples below continue to work unchanged. ReNamer preset import is
excluded.

## Text editing

Open a `.toml` backup in any UTF-8 text editor. Text goes in quotes, booleans are
`true` or `false`, and numbers are unquoted. Each `[[rules]]` starts another rule;
its `[rules.options]` section follows immediately. Rules run in document order.
Comments begin with `#`. Comments are regenerated on the next backup, rather than
preserved verbatim. The file has a maximum of 100 rules and a 32 MiB size limit.

```toml
version = 1
name = "Listing photos"

[[rules]]
kind = "accents"
target = "stem"
enabled = true

[[rules]]
kind = "cleanup"
target = "stem"
enabled = true
[rules.options]
trim = true
collapse = true
separator = "-"

[[rules]]
kind = "case"
target = "name"
enabled = true
[rules.options]
mode = "lower"
```

Targets are `stem` (name without its final extension), `extension`, and `name`
(complete filename). Change extension and Repair filename have their own fixed
scope. Disabled rules remain in the backup. Unknown rule kinds, options, and
invalid option types are rejected without changing current rules or saved presets.
Problems dependent on a particular filename, such as missing rearrangement parts,
appear during preview.

For regex text, TOML literal single-quoted strings avoid doubling backslashes:

```toml
[[rules]]
kind = "regex"
[rules.options]
pattern = '^(.*)_(\d+)$'
replacement = '\g<2>_\g<1>'
```

Literal Remove/Replace rules accept `occurrence = "first"`, `"last"`, or `"all"`.
Older presets use `all = true/false`; `occurrence = "legacy"` preserves that
setting. An explicit first/last/all value takes precedence. Newline and tab
characters in filenames are displayed as escaped codes in the Files table.

## Practical examples

- Rearrange parts: delimiter `_`, arrangement `{2}_{1}` changes `blue_jacket.jpg`
  to `jacket_blue.jpg`. Empty parts are retained. `{{` and `}}` produce literal
  braces; missing part numbers are errors rather than silently lost text.
- Delete text: `between` removes text between the first start delimiter and the
  first subsequent end delimiter. Delimiters remain unless explicitly included.
  A missing delimiter leaves that filename unchanged. Right-counting applies to
  position/count mode; zero means the right edge.
- Remove accents: `café` becomes `cafe`; Greek and other scripts are preserved.
  This is not general transliteration, and letters such as `ø` remain unchanged.
- Repair filename: `Windows-compatible` changes `CON.txt` to `_CON.txt`, replaces
  prohibited characters with `_`, and trims trailing dots/spaces. `This computer`
  uses the current OS. Linux keeps a literal backslash. Length errors and
  destination collisions still require a rule change or exclusion.

Backups can be moved between Windows and Linux. Normal transformations are
identical for identical inputs and numbering order. The explicit native repair
mode and destination filesystem validation intentionally depend on the host.
