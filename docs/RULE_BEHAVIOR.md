# File Renamer behavior and compatibility

These notes describe File Renamer's version-2 rule behavior and its limits.
For the exact source and validation evidence for a download, use that release's
notes, build information, and checksum files. Tests of File Renamer do not
establish equivalence with another application.

## Rules and saved presets

File Renamer provides 18 rule families plus Repair filename. The
[README rule table](../README.md#rules) describes their options; definitions and
defaults are in `src/file_renamer/registry.py`.

New rules use one-based positions and offer **Skip extension** where applicable.
The extension is the final suffix: `archive.tar.gz` has extension `gz`.
Regular Expressions uses native Unicode TRegExpr syntax, with `$1`, `$2`, and
`$0` for captured groups and the whole match.

Version-1 presets retain their original options and behavior, including
zero-based positions, Python regular expressions, and Latin accent removal.
Their editors show **Legacy**. Version-2 preset backups record behavior for each
rule, allowing legacy and newer rules in the same job. See
[editable preset examples](PRESETS.md) for the saved format.

Preset import from other applications is not supported. Similar rule names do not make presets,
regular-expression replacements, scripts, or metadata results interchangeable.
Full behavioral or layout equivalence with other applications has not been verified.
Test adapted rules on disposable copies and inspect File Renamer's preview
before applying them to important files.

## Scripts and metadata

Pascal Script uses the bundled RemObjects Pascal Script runtime. Available
functions are listed in `src/file_renamer/assets/pascal-functions.json`, generated from the
helper's registrations and support declarations. The editor supplies short
examples; custom scripts must use functions available in this application.

Script and native regular-expression calls have five-second deadlines and an
internal watchdog. Script file reads are bounded at 1 MiB. File writes, DLL
imports, process execution, script dialogs, changing the current directory,
and clipboard writes are excluded from the script API. Numbering, mapping
usage, random generation, and Pascal state reset for each preview; generated
random destinations remain fixed until Rename.

The metadata picker contains 140 tag identifiers in `src/file_renamer/assets/metadata-tags.json`.
ExifTool reads media, document, font, and executable metadata. Separate adapters
read file information, hashes, HTML, EML, torrents, and APK manifests. Missing
readable fields are empty; extraction failures become preview errors.
ExifTool extraction has a 30-second per-file deadline. The GUI limits version-2
preview batches to two minutes. Reader output can differ from other tools.

The packaged application includes its native helper, ExifTool, and
platform-specific Perl runtime. Another renaming application or a separate Perl
installation is not required. See [third-party notices](../THIRD_PARTY_NOTICES.md)
for component attribution and licenses.

## Platform limits

Windows ANSI/OEM functions use host code pages; Linux uses UTF-8. DOS paths are
unavailable on Linux. Missing creation timestamps report a filesystem limitation.

Repair filename offers **This computer** and **Windows-compatible** policies.
Valid native Unicode and punctuation are preserved by default. Actual filesystem
restrictions still apply; a Linux-mounted filesystem can impose different limits
from ext4. Neither policy automatically resolves collisions or truncates names.

Useful platform references:

- [Microsoft filename conventions](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
- [Linux pathname requirements](https://man7.org/linux/man-pages/man7/pathname.7.html)
- [Qt standard storage locations](https://doc.qt.io/qt-6/qstandardpaths.html)

## About these notes

File Renamer is maintained by Steady State Studio.

These notes describe version-2 rule behavior and package limits.
See [validation](VALIDATION.md) for the scope and limitations of recorded checks.
