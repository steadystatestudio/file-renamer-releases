"""User-facing compact forms, appearance overrides and native choice semantics."""
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QResizeEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QButtonGroup, QCheckBox, QFrame, QRadioButton

from file_renamer.choice_buttons import AccentCheckBox, AccentRadioButton, _contrast, _foreground
from file_renamer.dialogs import EDITOR_WIDTHS_KEY, TEXT_EDITOR_KINDS, RuleDialog, SavePresetDialog, SettingsDialog
from file_renamer.gui import MainWindow
from file_renamer.models import RuleSpec


@pytest.fixture
def compact_window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "_message", lambda *args: None)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    window = MainWindow(tmp_path / "data", settings)
    window.show()
    for _ in range(3):
        app.processEvents()
    yield window
    window.close()
    app.processEvents()


def settle(app):
    for _ in range(6):
        app.processEvents()


def test_button_choices_retain_native_roles_tristate_and_keyboard(app):
    checkbox = AccentCheckBox("Include selected items")
    checkbox.setTristate(True)
    checkbox.resize(checkbox.sizeHint())
    checkbox.show()
    assert isinstance(checkbox, QCheckBox)
    QTest.mouseClick(checkbox, Qt.LeftButton, pos=QPoint(checkbox.width() - 3, checkbox.height() // 2))
    assert checkbox.checkState() == Qt.PartiallyChecked
    assert "Mixed" in checkbox._label()
    checkbox.setFocus()
    QTest.keyClick(checkbox, Qt.Key_Space)
    assert checkbox.checkState() == Qt.Checked
    group = QButtonGroup()
    first, second = AccentRadioButton("First"), AccentRadioButton("Second")
    for button in (first, second):
        assert isinstance(button, QRadioButton)
        group.addButton(button)
        button.show()
    first.setChecked(True)
    second.click()
    assert second.isChecked() and not first.isChecked()
    # Painting must use readable text even for a pale system accent.
    assert _contrast(QColor("#ff9fc5"), _foreground(QColor("#ff9fc5"), QColor("white"))) >= 4.5
    assert not checkbox.grab().isNull()
    for widget in (checkbox, first, second):
        widget.close()


def test_minimum_row_stops_at_neighbors_and_has_no_extra_rules_box(app, compact_window):
    window = compact_window
    row = window.action_row
    window.resize(window.minimumWidth(), window.height())
    settle(app)
    assert window.minimumWidth() < 900 * max(1, window.fontMetrics().height() / 16)
    assert row.height() == row.height_for_width(row.width())
    assert window.rule_controls.geometry().right() < window.rename.geometry().left()
    assert window.rename.geometry().right() < window.undo.geometry().left()
    narrow_height = row.height()
    window.resize(window.width() + 350, window.height())
    settle(app)
    assert row.height() == narrow_height
    assert not window.findChildren(QFrame, "panel")


class UserResize(QResizeEvent):
    def spontaneous(self):
        return True


def choose(dialog, kind):
    for row in range(dialog.kind.count()):
        if dialog.kind.item(row).data(Qt.UserRole) == kind:
            dialog.kind.setCurrentRow(row)
            return
    raise AssertionError(kind)


def test_editor_preference_survives_modes_restart_and_screen_clamping(app, compact_window, monkeypatch):
    window = compact_window
    dialog = RuleDialog(window, RuleSpec("insert", behavior="renamer"))
    area = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1200))
    monkeypatch.setattr(dialog.screen(), "availableGeometry", lambda: area.availableGeometry())
    dialog.show()
    settle(app)
    assert dialog.maximumWidth() > dialog.minimumWidth()
    wanted = max(dialog.width() + 140, 850)
    dialog.resizeEvent(UserResize(QSize(wanted, dialog.height()), dialog.size()))
    settle(app)
    preferred = json.loads(window.settings.value(EDITOR_WIDTHS_KEY))["insert"]
    assert preferred > 400
    choose(dialog, "padding")
    settle(app)
    assert dialog.minimumSize() == dialog.maximumSize()
    choose(dialog, "insert")
    settle(app)
    restored_width = dialog.width()
    assert abs(restored_width - wanted) <= 2
    area.availableGeometry = lambda: QRect(0, 0, 800, 600)
    dialog._screen_changed()
    settle(app)
    assert dialog.width() <= 760
    assert json.loads(window.settings.value(EDITOR_WIDTHS_KEY))["insert"] == preferred
    dialog.close()
    reopened = RuleDialog(window, RuleSpec("insert", behavior="renamer"))
    monkeypatch.setattr(reopened.screen(), "availableGeometry", lambda: QRect(0, 0, 1920, 1200))
    reopened.show()
    settle(app)
    assert abs(reopened.width() - restored_width) <= 2
    reopened.resize(reopened.width() + 20, reopened.height())
    settle(app)
    assert json.loads(window.settings.value(EDITOR_WIDTHS_KEY))["insert"] == preferred
    reopened.close()


@pytest.mark.parametrize("kind", sorted(TEXT_EDITOR_KINDS))
def test_only_text_heavy_editors_allow_horizontal_resize(app, compact_window, kind):
    dialog = RuleDialog(compact_window, RuleSpec(kind, behavior="renamer"))
    dialog.show()
    settle(app)
    assert dialog.minimumWidth() < dialog.maximumWidth()
    assert dialog.minimumHeight() == dialog.maximumHeight()
    assert dialog.editor_scroll.horizontalScrollBar().maximum() == 0
    dialog.close()


def test_fitted_form_has_no_manual_expansion(app, compact_window):
    dialog = SavePresetDialog("Example", compact_window)
    dialog.show()
    settle(app)
    assert dialog.minimumSize() == dialog.maximumSize()
    assert dialog.height() < compact_window.fontMetrics().height() * 12
    assert dialog.content_scroll.verticalScrollBar().maximum() == 0
    dialog.close()


def test_fitted_form_scrolls_only_body_on_genuinely_small_screen(app, compact_window, monkeypatch):
    dialog = SavePresetDialog("Example", compact_window)
    monkeypatch.setattr(dialog.screen(), "availableGeometry", lambda: QRect(0, 0, 300, 180))
    dialog.show()
    settle(app)
    assert dialog.height() <= 100
    assert dialog.content_scroll.verticalScrollBar().maximum() > 0
    assert dialog.rect().contains(dialog.layout().itemAt(1).widget().geometry())
    dialog.close()


def test_72_point_preset_form_keeps_actions_visible(app, compact_window, monkeypatch):
    from file_renamer.appearance import configure_appearance
    from file_renamer.themes import apply_theme

    settings = compact_window.settings
    keys = ("appearance/font_mode", "appearance/font_family", "appearance/font_size_pt")
    saved = {key: settings.value(key) for key in keys if settings.contains(key)}
    dialog = None
    try:
        settings.setValue("appearance/font_mode", "custom")
        settings.setValue("appearance/font_family", app.font().family())
        settings.setValue("appearance/font_size_pt", 72)
        configure_appearance(app, settings)
        apply_theme(app)
        dialog = SavePresetDialog("Example", compact_window)
        monkeypatch.setattr(dialog.screen(), "availableGeometry", lambda: QRect(0, 0, 1200, 500))
        dialog.show()
        settle(app)
        assert dialog.font().pointSizeF() == 72
        assert dialog.height() <= 420
        assert dialog.content_scroll.verticalScrollBar().maximum() > 0
        assert dialog.rect().contains(dialog.layout().itemAt(1).widget().geometry())
    finally:
        if dialog:
            dialog.close()
        for key in keys:
            settings.setValue(key, saved[key]) if key in saved else settings.remove(key)
        configure_appearance(app, settings)
        apply_theme(app)


def test_appearance_save_cancel_and_reset_preserve_unrelated_settings(app, compact_window):
    window = compact_window
    settings = window.settings
    settings.setValue("recursive", True)
    settings.setValue("unrelated", "retained")
    dialog = SettingsDialog(settings, window)
    controls = dialog.controls
    controls.font_mode.setCurrentIndex(controls.font_mode.findData("custom"))
    controls.font_size.setValue(18)
    controls.accent_mode.setCurrentIndex(controls.accent_mode.findData("custom"))
    controls.accent_color = QColor("#d84c8b")
    dialog.accept()
    assert settings.value("appearance/font_size_pt", type=float) == 18
    assert window.font().pointSizeF() == 18
    assert settings.value("appearance/accent") == "#d84c8b"
    canceled = SettingsDialog(settings, window)
    canceled.controls.font_size.setValue(27)
    canceled.recursive.setChecked(False)
    canceled.controls.reset_appearance_button.click()
    canceled.reject()
    assert settings.value("appearance/font_size_pt", type=float) == 18
    assert settings.value("recursive", type=bool)
    reset = SettingsDialog(settings, window)
    reset.controls.reset_appearance_button.click()
    assert reset.recursive.isChecked()
    reset.accept()
    assert settings.value("appearance/font_mode") == "system"
    assert settings.value("appearance/accent_mode") == "system"
    assert not settings.contains("appearance/font_size_pt")
    assert settings.value("unrelated") == "retained"
    assert settings.value("recursive", type=bool)
