# ReNamer rule implementation — October 2, 2026

File Renamer 2.0 contains all 18 rule families plus Repair filename. New editors
use the flat rule list and compact option groups, with visible radio choices,
checkboxes, inline position/delimiter fields, and natural-width action buttons.
Dialogs fit the selected editor, with readable 12-point text. Short screens
reflow choices and scroll vertically only when necessary; rule areas never
scroll horizontally. Pass 10 uses the feedback document screenshots as the
layout reference, with the app's own typography and colors.

The complete option definitions are in `src/file_renamer/registry.py`. Tests
verify all 18 editor round trips and behavior across every family. New jobs use
one-based positions, skip-extension options and native Unicode TRegExpr syntax.
Version-1 presets keep their original options and behavior, with Legacy shown
in the editor. Version-2 presets record behavior independently for every rule.
ReNamer preset import is excluded.

The native helper uses real RemObjects Pascal Script maintained with Lazarus
2.2.0 and compiled by Free Pascal 3.2.2. The generated
`assets/pascal-functions.json` lists registered naming/read-only functions used
for completion. They cover strings, Unicode, arrays, conversions, dates, regex,
metadata, file reads/scans, preview indexes and scalar shared variables.
File reads are bounded at 1 MiB. Numbering, mapping usage, random and Pascal
state reset for each preview; random destinations are frozen until Rename.

Native script/regex calls have a five-second deadline and internal watchdog.
Metadata extraction has a 30-second per-file deadline and two-minute GUI batch
deadline. File writes, DLL imports, process execution, script dialogs, changing
the current directory and clipboard writes are excluded. Windows ANSI/OEM
functions use host code pages; Linux uses UTF-8. DOS paths are unavailable on
Linux; missing creation timestamps report a filesystem limitation.

The full 140-tag catalog is in `assets/metadata-tags.json`. Bundled ExifTool
13.59 reads media, documents, fonts and executable metadata; dedicated adapters
read file data, hashes, HTML, EML, torrents and APK manifests. Missing readable
fields are empty; extraction failures become preview errors. Reader details can
differ from ReNamer. Packaged builds include the native helper, ExifTool and
platform-specific Perl runtime; installed ReNamer/Perl are unnecessary.

Built-in alphabet and script examples are independent examples. Users can load
their own maps/scripts, including their existing reference resources. No
proprietary ReNamer source or artwork is bundled. Reference names/options were
checked against installed resources and official documentation. Live reference
interaction was unavailable, so complete byte-for-byte equivalence is not
claimed. See [validation](VALIDATION.md) for both platform suites and bundle checks.

## Historical version-1.1 review — September 14, 2026

The narrower decisions below describe the previous release, not version 2.0.

Downloaded the official portable package from
https://www.den4b.com/download/renamer/portable into a temporary research directory.
The executable reports **7.10.0.0**. No third-party code or artwork was copied.

Sources: [current rule documentation](https://www.den4b.com/docs/books/renamer),
[screenshots](https://www.den4b.com/screenshots/renamer), and the downloaded
package's English source strings in `Languages/ReNamer.de.po`.

**Verification limitation:** the Windows Computer Use native pipe was unavailable
after retry and reset. The live rule selector and disposable-file examples could
not be exercised. This comparison is documentation/resource inspection, not a
claim of complete live equivalence.

| ReNamer rule family | File Renamer 1.1 decision |
|---|---|
| Insert, Delete | Extend existing text rules with literal match/delimiter options |
| Remove, Replace | Add first/last/all non-overlapping literal occurrences |
| Rearrange | Add numbered delimiter-separated parts; omit metadata and position splitting |
| Extension | Retain explicit extension replacement/removal; omit binary signature detection |
| Strip | Add Unicode category sets and literal custom characters |
| Case, Serialize, Padding | Retain existing case, numbering, and numeric padding rules |
| Clean Up | Retain whitespace/separator cleanup; add separate explicit filename repair |
| Translit | Offer narrow Latin accent removal; defer alphabet transliteration/maps |
| Regular Expressions | Retain Python syntax and isolated evaluation deadline |
| Randomize, Pascal Script | Defer; unnecessary complexity for this release |
| User Input, Mapping | Defer pasted lists and filename mappings |
| Reformat Date | Defer date parsing and metadata-based naming |

The current docs describe **18 rule families**, including Mapping; the old wiki
lists 17. Downloaded language resources also contain Mapping controls. Our
compatibility choices are intentionally narrower; presets and regex replacement
syntax are not interchangeable with ReNamer.

Platform references:

- [Microsoft filename conventions](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
- [Linux pathname requirements](https://man7.org/linux/man-pages/man7/pathname.7.html)
- [Qt standard Documents location](https://doc.qt.io/qt-6/qstandardpaths.html)

File Renamer adds an explicit native/Windows-compatible repair choice and preserves
valid native Unicode and punctuation by default. Filesystem restrictions remain
authoritative; this is not a promise that every Linux-mounted filesystem accepts
all filenames accepted by ext4.

## Rule picker alignment ? 2026-10-02

The picker now uses a flat list with ReNamer display names and relative order for
supported rule families. Repair filename remains an app-specific final entry.
Translit maps to the existing Latin accent removal rule; its description states
that limit. Internal identifiers, saved presets, and rule behavior are unchanged.
This is presentation alignment, not full rule or preset compatibility.


## Existing editor presentation ? 2026-10-02 feedback

Existing rule editors now use explicit sections and readable choice labels, based
on the installed ReNamer English source strings. Fields span the available editor
width, labels wrap, and vertical scrolling accommodates short screens. Both the
main Rules table and rule editor prohibit horizontal scrolling while fitting
content to their width. Boolean controls use highlighted buttons throughout.

Rule behavior, internal option identifiers, preset formats, zero-based positions,
Python regex syntax, and the Latin-only Translit limitation remain unchanged.
No additional ReNamer options or rule families were added. The installed reference
launch attempt did not expose a targetable window, so this is resource-based
presentation alignment, not verified live layout equivalence.
