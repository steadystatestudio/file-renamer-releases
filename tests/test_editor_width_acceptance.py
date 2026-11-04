"""Acceptance checks for remembered editor widths and safe preset selection."""
import json
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect, QSettings, Qt, QTimer
from PySide6.QtGui import QResizeEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QWidget

from file_renamer.appearance import configure_appearance
from file_renamer.dialogs import (
    EDITOR_WIDTHS_KEY,
    TEXT_EDITOR_KINDS,
    ChoiceGroup,
    LoadPresetDialog,
    RuleDialog,
)
from file_renamer.gui import MainWindow
from file_renamer.models import RuleSpec
from file_renamer.themes import apply_theme

EDITORS = (
    "insert", "remove", "replace", "rearrange", "regex",
    "translit", "pascal", "userinput", "mapping",
)


@pytest.fixture
def editor_window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "_message", lambda *_: None)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    window = MainWindow(tmp_path / "data", settings)
    window.show()
    settle(app, window)
    yield window
    for child in window.findChildren(QDialog):
        child.close()
    for key in ("appearance/font_mode", "appearance/font_family", "appearance/font_size_pt"):
        settings.remove(key)
    settings.setValue("theme", "system")
    configure_appearance(app, settings)
    apply_theme(app, "system")
    window.close()
    app.processEvents()


def settle(app, widget):
    """Wait for stable layout, including queued height and appearance fitting."""
    deadline = time.monotonic() + 4
    previous, stable = None, 0
    while time.monotonic() < deadline:
        app.processEvents()
        signature = (widget.size().toTuple(), widget.minimumSize().toTuple(),
                     widget.maximumSize().toTuple(), widget.fontInfo().pixelSize())
        timer = getattr(widget, "fit_timer", None)
        stable = stable + 1 if signature == previous and not (timer and timer.isActive()) else 0
        if stable >= 5:
            return
        previous = signature
        QTest.qWait(15)
    raise AssertionError("Editor layout did not settle")


def preferences(settings):
    settings.sync()
    return json.loads(settings.value(EDITOR_WIDTHS_KEY, "{}"))


def choose(dialog, kind, app):
    for row in range(dialog.kind.count()):
        if dialog.kind.item(row).data(Qt.UserRole) == kind:
            dialog.kind.setCurrentRow(row)
            settle(app, dialog)
            return
    raise AssertionError("Missing rule editor: " + kind)


def open_editor(parent, kind, area, app, monkeypatch):
    dialog = RuleDialog(parent, RuleSpec(kind, behavior="renamer"))
    monkeypatch.setattr(dialog.screen(), "availableGeometry", lambda: area.availableGeometry())
    dialog.show()
    settle(app, dialog)
    return dialog


class UserResize(QResizeEvent):
    def spontaneous(self):
        return True


def user_width(dialog, pane_width, app):
    # Model a window-manager resize at Qt's event boundary, without host input.
    # Native spontaneous resizing/restart is independently covered for Insert.
    old = dialog.size()
    dialog.resize(dialog.width() + pane_width - dialog.editor_scroll.width(), dialog.height())
    settle(app, dialog)
    dialog.resizeEvent(UserResize(dialog.size(), old))
    settle(app, dialog)
    assert abs(dialog.editor_scroll.width() - pane_width) <= 2


def test_all_nine_editors_remember_independent_widths_and_reopen_from_disk(
    app, editor_window, monkeypatch,
):
    assert set(EDITORS) == TEXT_EDITOR_KINDS
    area = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 2400, 1500))
    dialog = open_editor(editor_window, EDITORS[0], area, app, monkeypatch)
    expected = {}
    for number, kind in enumerate(EDITORS):
        choose(dialog, kind, app)
        wanted = 1000 + 37 * number
        user_width(dialog, wanted, app)
        saved = preferences(editor_window.settings)
        assert abs(saved[kind] - wanted) <= 2
        assert all(saved[key] == width for key, width in expected.items())
        expected[kind] = saved[kind]
        # Visiting a fitted deleting page must not replace any editor's width.
        choose(dialog, "delete", app)
        assert dialog.minimumSize() == dialog.maximumSize()
        assert preferences(editor_window.settings) == expected
    assert len(set(expected.values())) == 9
    dialog.close()

    # A fresh settings reader proves persistence, rather than an in-memory cache.
    parent = QWidget(editor_window)
    parent.settings = QSettings(editor_window.settings.fileName(), QSettings.IniFormat)
    assert preferences(parent.settings) == expected
    for kind in reversed(EDITORS):
        reopened = open_editor(parent, kind, area, app, monkeypatch)
        assert abs(reopened.editor_scroll.width() - expected[kind]) <= 2
        assert preferences(parent.settings) == expected
        reopened.close()
    parent.close()


@pytest.mark.parametrize("kind", EDITORS)
def test_editor_width_survives_modes_font_theme_and_temporary_smaller_work_area(
    app, editor_window, monkeypatch, kind,
):
    area = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 2400, 1500))
    dialog = open_editor(editor_window, kind, area, app, monkeypatch)
    user_width(dialog, 1200 + EDITORS.index(kind) * 11, app)
    saved = preferences(editor_window.settings)
    preferred = saved[kind]

    # Exercise actual option modes where the editor has them, then visit a fitted
    # deleting page and return. Neither navigation nor fitting is a user resize.
    modes = [widget for widget in dialog.widgets.values()
             if isinstance(widget, ChoiceGroup) and len(widget.values) > 1]
    for mode in modes:
        initial = mode.group.checkedId()
        mode.setCurrentIndex((initial + 1) % len(mode.values))
        settle(app, dialog)
        assert preferences(editor_window.settings) == saved
        mode.setCurrentIndex(initial)
    choose(dialog, "delete", app)
    choose(dialog, kind, app)
    assert abs(dialog.editor_scroll.width() - preferred) <= 2

    settings = editor_window.settings
    settings.setValue("appearance/font_mode", "custom")
    settings.setValue("appearance/font_family", app.font().family())
    settings.setValue("appearance/font_size_pt", 18)
    for theme in ("dark", "light"):
        configure_appearance(app, settings)
        apply_theme(app, theme)
        settle(app, dialog)
        assert dialog.font().pointSizeF() == 18
        assert preferences(settings) == saved
    area.availableGeometry = lambda: QRect(0, 0, 1100, 800)
    dialog._screen_changed()
    settle(app, dialog)
    assert dialog.width() <= 1060
    assert preferences(settings) == saved
    dialog.close()

    parent = QWidget(editor_window)
    parent.settings = QSettings(settings.fileName(), QSettings.IniFormat)
    reopened = open_editor(parent, kind, area, app, monkeypatch)
    assert preferences(parent.settings) == saved
    assert reopened.width() <= 1060
    area.availableGeometry = lambda: QRect(0, 0, 2400, 1500)
    reopened._screen_changed()
    settle(app, reopened)
    assert abs(reopened.editor_scroll.width() - preferred) <= 2
    assert preferences(parent.settings) == saved
    reopened.close()
    parent.close()


def test_empty_preset_picker_disables_load_and_empty_menu_is_guarded(
    app, editor_window, monkeypatch,
):
    window = editor_window
    assert not window.presets.presets
    menu = window._make_preset_menu()
    load = next(action for action in menu.actions() if action.text() == "Load")
    assert not load.isEnabled()
    calls = []
    monkeypatch.setattr(LoadPresetDialog, "exec", lambda self: calls.append(self) or QDialog.Rejected)
    before = (list(window.rules), window.selected_preset, window.preset_label.text())
    window._choose_preset()
    assert calls == []
    dialog = LoadPresetDialog({}, parent=window)
    dialog.show()
    settle(app, dialog)
    assert dialog.choices.count() == 0 and dialog.selected_name == ""
    assert not dialog.load_button.isEnabled()
    QTest.mouseClick(dialog.load_button, Qt.LeftButton)
    assert dialog.isVisible()
    QTest.keyClick(dialog, Qt.Key_Escape)
    assert dialog.result() == QDialog.Rejected and not dialog.isVisible()
    assert (list(window.rules), window.selected_preset, window.preset_label.text()) == before
    menu.close()


def test_cancel_real_preset_picker_keeps_active_rules_and_identity(app, editor_window):
    window = editor_window
    window.presets.save("Active", [RuleSpec("case")])
    window.presets.save("Other", [RuleSpec("insert", options={"text": "new_"})])
    window._load_preset("Active")
    before = (list(window.rules), window.selected_preset, window.preset_label.text())
    errors = []

    def cancel_picker():
        dialog = app.activeModalWidget()
        try:
            assert isinstance(dialog, LoadPresetDialog)
            assert dialog.choices.count() == 2
            other = next(row for row in range(dialog.choices.count())
                         if dialog.choices.item(row).text() == "Other")
            dialog.choices.setCurrentRow(other)
            assert dialog.load_button.isEnabled()
            QTest.keyClick(dialog, Qt.Key_Escape)
        except Exception as exc:
            errors.append(repr(exc))
        finally:
            if dialog and dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(0, cancel_picker)
    window._choose_preset()
    assert not errors
    assert (list(window.rules), window.selected_preset, window.preset_label.text()) == before
