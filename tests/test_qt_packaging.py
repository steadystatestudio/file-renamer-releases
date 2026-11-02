import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("linux", [False, True])
def test_qt_hook_filters_only_linux_tiff_decoder_before_analysis(monkeypatch, linux):
    binaries = [(f"/qt/plugins/imageformats/{name}", "PySide6/Qt/plugins/imageformats")
                for name in ["libqjpeg.so", "libqtiff.so", "libqsvg.so", "qtiff.dll"]]
    binaries += [(f"/qt/plugins/other/{name}", "PySide6/Qt/plugins/other")
                 for name in ["libqpdf.so", "libqtvirtualkeyboardplugin.so", "libqtuiotouchplugin.so",
                              "libqvnc.so", "libqgtk3.so"]]
    upstream = {"hiddenimports": ["PySide6.QtSvg"], "datas": [("translation.qm", "translations")],
                "binaries": binaries}
    monkeypatch.setitem(sys.modules, "PyInstaller",
                        SimpleNamespace(compat=SimpleNamespace(is_linux=linux)))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks.qt", SimpleNamespace(
        add_qt6_dependencies=lambda path: (upstream["hiddenimports"], binaries, upstream["datas"])))
    spec = importlib.util.spec_from_file_location("qt_gui_hook", ROOT / "packaging/hooks/hook-PySide6.QtGui.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert hook.hiddenimports == upstream["hiddenimports"] and hook.datas == upstream["datas"]
    assert hook.binaries == ([binaries[0], *binaries[2:4]] if linux else binaries[:4])
    assert len(upstream["binaries"]) == 9


def test_tiff_fixture_is_valid_independent_of_metadata_reader():
    from PySide6.QtGui import QImage

    from file_renamer.smoke import tiff_fixture

    image = QImage.fromData(tiff_fixture(), "TIFF")
    assert not image.isNull() and (image.width(), image.height()) == (2, 3)
    assert image.pixelColor(0, 0).red() == 0 and image.pixelColor(1, 2).red() == 255
