import pytest
from PySide6.QtGui import QFont

from file_renamer import system_fonts


@pytest.mark.parametrize("dpi,scale,expected", [(96, 1, 11), (96, 1.5, 16.5), (144, 1.5, 11)])
def test_desktop_font_tracks_text_scale_without_double_scaling(dpi, scale, expected):
    result = system_fonts.desktop_font(QFont("Sans Serif", 9), "Noto Sans 11", scale, dpi)
    assert result.family() == "Noto Sans"
    assert result.pointSizeF() == pytest.approx(expected)


def test_desktop_font_preserves_style_and_multiword_family():
    result = system_fonts.desktop_font(QFont(), "Noto Sans Bold Italic 13.5", 1, 96)
    assert result.family() == "Noto Sans"
    assert result.bold() and result.italic()
    assert result.pointSizeF() == 13.5


@pytest.mark.parametrize("description,scale", [("invalid", 1), ("Sans 0", 1), ("Sans 12", float("nan"))])
def test_invalid_desktop_setting_preserves_native_font(description, scale):
    native = QFont("Native UI", 14)
    assert system_fonts.desktop_font(native, description, scale, 96) == native


def test_stylesheet_baseline_includes_native_tables_and_new_dialogs(tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QDialog, QTableWidget

    from file_renamer.appearance import configure_appearance

    app = QApplication.instance() or QApplication([])
    previous_font, previous_style = QFont(app.font()), app.styleSheet()
    previous_settings = getattr(app, "_studio_pilot_settings", None)
    settings = QSettings(str(tmp_path / "appearance.ini"), QSettings.IniFormat)
    try:
        chosen = QFont("Sans Serif", 18)
        settings.setValue("appearance/font_mode", "custom")
        settings.setValue("appearance/font_family", chosen.family())
        settings.setValue("appearance/font_size_pt", 18)
        configure_appearance(app, settings)
        app.setStyleSheet("QWidget {" + system_fonts.system_font_css(app) + "color: #222;}"
                         "QHeaderView::section { padding: 9px; }")
        dialog = QDialog()
        table = QTableWidget(2, 2, dialog)
        dialog.ensurePolished()
        table.ensurePolished()
        app.processEvents()
        for widget in (dialog, table, table.horizontalHeader(), table.verticalHeader()):
            assert widget.font().pointSizeF() == 18
            assert widget.font().family() == chosen.family()
        dialog.close()
    finally:
        configure_appearance(app, previous_settings)
        app.setStyleSheet(previous_style)
        app.setFont(previous_font)
