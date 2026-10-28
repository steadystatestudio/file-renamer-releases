# Third-party notices

File Renamer is MIT licensed. Its visual direction was inspired by
Square Photo Padder,
Copyright (c) 2026 Steady State Studio, also MIT licensed. This implementation uses
original application code and artwork. ReNamer was a functional reference; no
ReNamer code or assets are included.

TOML backup writing uses Tomli-W 1.2.0 (MIT): https://github.com/hukkin/tomli-w.
Its license is included in the bundle.

The portable application bundles Python and dynamically linked PySide6/Qt and
Shiboken components. Their own licenses apply, including the Python Software
Foundation license and the LGPL/GPL/commercial options provided by Qt.
Installed dependency license texts are copied into the bundle's `licenses` folder.
The LGPLv3 and GPLv3 texts from Qt's v6.11.0 source tree are included there as well.
`BUILD-INFO.txt` records the exact bundled Python, PySide6, and Shiboken versions.
Python's license is also retained in PyInstaller's runtime bundle when supplied by
the platform distribution. The libraries remain separate files in `_internal`.

Upstream projects and corresponding source distributions:

- Python: https://www.python.org/downloads/source/
- Qt for Python / PySide6: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Qt: https://code.qt.io/cgit/qt/
- PyInstaller and its bootloader exception: https://pyinstaller.org/en/stable/license.html

Build dependencies such as pytest, Ruff, and Pillow are development tools and are
not application dependencies. Linux AppImage packaging includes the AppImage runtime.

The naming runtime is made using RemObjects Pascal Script:
https://github.com/remobjects/pascalscript. The bundled source is the Lazarus
2.2.0 maintained variant. Its license is in `native/vendor/pascalscript/LICENSE.md`
and is copied into the application tools directory.

Metadata uses ExifTool 13.59 by Phil Harvey, https://exiftool.org/ (Perl Artistic
License or GPL). Its Perl runtime and license notices are bundled with the tools.
Pascal compilation uses Free Pascal 3.2.2; the runtime library is distributed
under the modified LGPL with its static linking exception:
https://www.freepascal.org/faq.html#general-license.

## Public distribution sources and library replacement

Qt/PySide6/Shiboken6 remain at the previously validated 6.11.0 versions. The
LGPLv3 alternative is used. Separate dynamic libraries can be replaced with
compatible modified libraries; reverse engineering for debugging those
modifications is not restricted by this application. See
`LIBRARY-REPLACEMENT.txt`, `SOURCE-INDEX.json`, and `LICENSE-INDEX.json` in each
package. The matching complete Qt and pyside-setup sources, including their
build scripts and upstream notices, must remain downloadable beside the public
packages. Exact official URLs and hashes are in `packaging/source-archives.json`.
No Studio modifications are made to these libraries.

The AppImage runtime is release 20251108, commit
`dd6cebedcbddde9c82f89b011e8e1d40b6e43868`. Its MIT license and static dependency
notices are in `licenses/appimage` and `APPIMAGE_RUNTIME_LICENSE.txt`. Matching
runtime, patched libfuse 3.15.0 and squashfuse 0.5.2 sources are retained beside
the release. Upstream's other Alpine library revisions were not fully pinned;
this is not a reproducible-build claim.

Linux system libraries discovered by PyInstaller are left on the host using
its supported `Analysis.exclude_system_libraries` API. Their Ubuntu package
names are recorded in `LINUX-SYSTEM-DEPENDENCIES.json`. A desktop and these
libraries are still required; an AppImage is not independent of its host OS.
Qt, Python and the offline metadata tools remain bundled. The Perl and ExifTool
standard libraries and copyright notices are retained with the tools.

The packaging-only Qt subset hooks, system-library manifest, source downloader,
release-staging checks and library-replacement instructions are adapted from
Steady State Studio's MIT-licensed Contact Sheet Maker public release tooling.
The application interface and rule behavior are otherwise unchanged.
