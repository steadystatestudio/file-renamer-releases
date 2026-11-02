"""Use Qt discovery without unused PDF/keyboard/TUIO/VNC/GTK/TIFF plugins.

File Renamer uses Qt to paint widgets and its SVG icon, not to decode user images.
Image/TIFF metadata is read by ExifTool. The Qt 6.11.0 TIFF plugin needs
libtiff.so.5, which Ubuntu 24.04 does not provide. Filter the plugin before
dependency analysis so its unused ABI does not become a host prerequisite.
Native input-method plugins and the existing narrow exclusions are preserved.
"""
from pathlib import Path

from PyInstaller import compat
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
# The application explicitly uses Fusion; the GTK platform theme is unused.
_excluded = ("qpdf.", "qtvirtualkeyboardplugin.", "qtuiotouchplugin.", "qvnc.", "qgtk3.")
binaries = [entry for entry in binaries
            if not Path(entry[0]).name.lower().removeprefix("lib").startswith(_excluded)]
if compat.is_linux:
    binaries = [entry for entry in binaries
                if not (Path(entry[0]).name == "libqtiff.so" and Path(entry[0]).parent.name == "imageformats")]
