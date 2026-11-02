"""Exercise first-time rule creation through the controls used by the desktop UI."""
import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QMessageBox, QPushButton, QSpinBox

from file_renamer.compat_rules import Evaluation
from file_renamer.dialogs import ChoiceGroup, RuleDialog, SavePresetDialog
from file_renamer.gui import MainWindow
from file_renamer.models import RuleSpec
from file_renamer.rule_controls import MappingEditor
from file_renamer.rules import RULE_ORDER, apply_rule

# Each example has a nondefault setting, an independently specified result, and an edit.
CASES = [
    ("insert", "photo.jpg", {"text": "new_"}, "new_photo.jpg", {"text": "edited_"}, "edited_photo.jpg"),
    ("delete", "abcde.txt", {"start": 2, "count": 2}, "ade.txt", {"count": 1}, "acde.txt"),
    ("remove", "catAbAB.txt", {"text": "ab", "occurrence": "last"}, "catAb.txt",
     {"occurrence": "first"}, "catAB.txt"),
    ("replace", "a b a.txt", {"find": "a", "replacement": "x", "occurrence": "first"}, "x b a.txt",
     {"replacement": "y"}, "y b a.txt"),
    ("rearrange", "blue_jacket.txt", {"delimiter": "_", "template": "$2-$1"}, "jacket-blue.txt",
     {"template": "$1-$2"}, "blue-jacket.txt"),
    ("extension", "file.txt", {"text": "jpg", "append": True}, "file.txt.jpg", {"text": "png"}, "file.txt.png"),
    ("strip", "001abc123.txt", {"digits": True, "position": "trailing"}, "001abc.txt",
     {"position": "leading"}, "abc123.txt"),
    ("case", "blue jacket.TXT", {"mode": "upper", "extension_case": "lower"}, "BLUE JACKET.txt",
     {"mode": "lower"}, "blue jacket.txt"),
    ("number", "photo.jpg", {"start": 12, "pad": True, "width": 3}, "012photo.jpg",
     {"start": 20}, "020photo.jpg"),
    ("randomize", "photo.jpg", {"digits": False, "use_characters": True, "characters": "X",
                                 "length": 3, "position": "suffix"}, "photoXXX.jpg",
     {"length": 2}, "photoXX.jpg"),
    ("padding", "file7.txt", {"width": 4}, "file0007.txt", {"width": 2}, "file07.txt"),
    ("cleanup", "a_b-c.txt", {"space_underscore": True}, "a b-c.txt", {"space_dash": True}, "a b c.txt"),
    ("translit", "abc.txt", {"alphabet": "a=x", "auto_case": False}, "xbc.txt", {"alphabet": "a=y"}, "ybc.txt"),
    ("date", "photo2024-03-02.txt", {"format": "dd-mm-yyyy"}, "photo02-03-2024.txt",
     {"format": "yyyy_mm_dd"}, "photo2024_03_02.txt"),
    ("regex", "photo12.txt", {"pattern": r"^(.+)(\d{2})$", "replacement": "$2-$1"}, "12-photo.txt",
     {"replacement": "$1-$2"}, "photo-12.txt"),
    ("pascal", "photo.jpg", {"script": "begin FileName := 'x_' + FileName; end."}, "x_photo.jpg",
     {"script": "begin FileName := 'y_' + FileName; end."}, "y_photo.jpg"),
    ("userinput", "photo.txt", {"names": "First\nSecond"}, "First.txt", {"names": "Edited\nSecond"}, "Edited.txt"),
    ("mapping", "old.txt", {"mapping": "old\tnew\n"}, "new.txt", {"mapping": "old\tedited\n"}, "edited.txt"),
    ("repair", "bad?.txt", {"platform": "Windows-compatible"}, "bad_.txt", {"platform": "This computer"},
     "bad_.txt" if os.name == "nt" else "bad?.txt"),
]


def button(parent, label):
    matches = [widget for widget in parent.findChildren(QPushButton) if widget.text() == label and widget.isVisible()]
    assert len(matches) == 1, (label, len(matches))
    return matches[0]


def type_text(widget, text):
    widget.setFocus()
    QTest.keyClick(widget, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(widget, Qt.Key_Backspace)
    for index, line in enumerate(text.split("\n")):
        if index:
            QTest.keyClick(widget, Qt.Key_Return)
        QTest.keyClicks(widget, line)


def set_options(dialog, options):
    for key, value in options.items():
        widget = dialog.widgets[key]
        dialog.editor_scroll.ensureWidgetVisible(widget)
        if isinstance(widget, ChoiceGroup):
            choice = widget.group.button(widget.findData(value))
            QTest.mouseClick(choice, Qt.LeftButton, pos=QPoint(8, choice.height() // 2))
        elif isinstance(widget, QCheckBox):
            if widget.isChecked() != value:
                QTest.mouseClick(widget, Qt.LeftButton, pos=QPoint(8, widget.height() // 2))
        elif isinstance(widget, MappingEditor):
            if not widget.table.rowCount():
                QTest.mouseClick(button(widget, "Add mapping"), Qt.LeftButton)
                QApplication.processEvents()
            for column, text in enumerate(value.rstrip("\n").split("\t")):
                widget.table.setCurrentCell(0, column)
                widget.table.setFocus()
                QApplication.processEvents()
                QTest.keyClick(widget.table, Qt.Key_F2)
                QApplication.processEvents()
                type_text(QApplication.focusWidget(), text)
                QTest.keyClick(QApplication.focusWidget(), Qt.Key_Tab)
                assert widget.table.item(0, column).text() == text
        else:
            type_text(widget, str(value))
            if isinstance(widget, QSpinBox):
                QTest.keyClick(widget, Qt.Key_Tab)
        QApplication.processEvents()


def modal_action(trigger, edit, dialog_type=RuleDialog, save_label="Add Rule"):
    errors = []

    def interact():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, dialog_type)
            edit(dialog)
            QTest.mouseClick(button(dialog, save_label), Qt.LeftButton)
            assert dialog.result() == QDialog.Accepted, "The editor rejected the entered rule"
        except Exception as error:
            errors.append(error)
        finally:
            if dialog and dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(0, interact)
    trigger()
    assert not errors, errors


def select_rule(dialog, kind):
    row = RULE_ORDER.index(kind)
    item = dialog.kind.item(row)
    dialog.kind.scrollToItem(item)
    QTest.mouseClick(dialog.kind.viewport(), Qt.LeftButton, pos=dialog.kind.visualItemRect(item).center())
    QApplication.processEvents()
    assert dialog._kind() == kind


def output(rule, name):
    context = Evaluation()
    try:
        return apply_rule(name, rule, 0, context=context)
    finally:
        for session in context.pascal.values():
            session.close()


def wait_idle(app, window):
    deadline = time.monotonic() + 15
    while window.busy or window.debounce.isActive() or window.process is not None:
        app.processEvents()
        assert time.monotonic() < deadline, "Preview did not finish"
        time.sleep(.005)
    app.processEvents()


@pytest.fixture
def editor_window(app, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, message: warnings.append((title, message)))
    monkeypatch.setattr(MainWindow, "_message", lambda self, title, message: warnings.append((title, message)))
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    window = MainWindow(tmp_path / "appdata", settings)
    window.show()
    app.processEvents()
    yield window
    wait_idle(app, window)
    window.close()
    app.processEvents()
    assert not warnings, warnings


@pytest.mark.parametrize("kind,name,options,expected,edit,edited", CASES, ids=[case[0] for case in CASES])
def test_create_edit_save_and_reload_rule(app, editor_window, kind, name, options, expected, edit, edited):
    window = editor_window
    assert not window.rules

    def configure(dialog):
        select_rule(dialog, kind)
        set_options(dialog, options)

    modal_action(lambda: QTest.mouseClick(button(window, "Add Rule"), Qt.LeftButton), configure)
    assert len(window.rules) == 1
    assert window.rules[0].target == ("name" if kind == "repair" else "stem")
    assert output(window.rules[0], name) == expected
    wait_idle(app, window)
    modal_action(lambda: QTest.mouseClick(button(window, "Edit"), Qt.LeftButton),
                 lambda dialog: set_options(dialog, edit), save_label="Save Rule")
    rule = window.rules[0]
    assert output(rule, name) == edited
    wait_idle(app, window)

    # Reopening the editor and saving unchanged must retain the user's edited values.
    modal_action(lambda: QTest.mouseClick(button(window, "Edit"), Qt.LeftButton),
                 lambda dialog: None, save_label="Save Rule")
    assert window.rules == [rule]
    wait_idle(app, window)

    # Use the real preset menu action/dialog, then clear and reload its stored rule.
    menu = window._make_preset_menu()
    save = next(action for action in menu.actions() if action.text() == "Save")
    modal_action(save.trigger, lambda dialog: type_text(dialog.name, "Created rule"),
                 dialog_type=SavePresetDialog, save_label="Save")
    assert window.presets.presets["Created rule"] == [rule]
    QTest.mouseClick(button(window, "Remove"), Qt.LeftButton)
    wait_idle(app, window)
    menu = window._make_preset_menu()
    next(action for action in menu.load_menu.actions() if action.data() == "Created rule").trigger()
    assert window.rules == [rule]
    wait_idle(app, window)
    window.close()
    app.processEvents()
    restored = MainWindow(window.data_dir, window.settings)
    try:
        assert restored.rules == [rule]
        assert restored.presets.presets["Created rule"] == [rule]
        assert output(restored.rules[0], name) == edited
    finally:
        restored.close()


@pytest.mark.parametrize("target", ["stem", "extension", "name"])
def test_edit_preserves_existing_legacy_target(app, editor_window, target):
    window = editor_window
    window.rules = [RuleSpec("insert", target=target, options={"text": "old_"})]
    window._fill_rules(0)
    modal_action(lambda: QTest.mouseClick(button(window, "Edit"), Qt.LeftButton),
                 lambda dialog: set_options(dialog, {"text": "kept_"}), save_label="Save Rule")
    assert window.rules[0].target == target
    assert window.rules[0].behavior == "legacy"
    assert output(window.rules[0], "photo.jpg") == {
        "stem": "kept_photo.jpg", "extension": "photo.kept_jpg", "name": "kept_photo.jpg",
    }[target]


def test_created_rules_reach_preview_rename_and_undo(app, editor_window, tmp_path):
    window = editor_window
    original = tmp_path / "photo.jpg"
    original.write_bytes(b"synthetic source content")
    window.add_paths([str(original)])
    wait_idle(app, window)

    def configure(dialog):
        set_options(dialog, {"text": "new_"})

    modal_action(lambda: QTest.mouseClick(button(window, "Add Rule"), Qt.LeftButton), configure)
    wait_idle(app, window)
    assert Path(window.model.plan.files[0].destination).name == "new_photo.jpg"
    QTest.mouseClick(window.rename, Qt.LeftButton)
    wait_idle(app, window)
    assert not original.exists()
    assert (tmp_path / "new_photo.jpg").read_bytes() == b"synthetic source content"
    QTest.mouseClick(window.undo, Qt.LeftButton)
    wait_idle(app, window)
    assert original.read_bytes() == b"synthetic source content"
    assert not (tmp_path / "new_photo.jpg").exists()
