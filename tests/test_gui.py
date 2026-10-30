import time
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest

from file_renamer.dialogs import RuleDialog
from file_renamer.gui import MainWindow
from file_renamer.models import RuleSpec
from file_renamer.registry import REGISTRY
from file_renamer.rules import RULE_DEFAULTS


@pytest.mark.parametrize("kind", list(REGISTRY))
def test_expanded_rule_editor_roundtrip(app, window, kind):
    definition = REGISTRY[kind]
    rule = RuleSpec(kind, behavior="renamer", options=definition.defaults)
    dialog = RuleDialog(window, rule)
    dialog.show()
    app.processEvents()
    assert set(dialog.widgets) == set(definition.defaults)
    dialog._accept()
    assert dialog.result_rule == rule
    dialog.close()


def wait_until(app, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert predicate(), "UI operation did not complete in time"


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(MainWindow, "_message", lambda self, title, message: messages.append((title, message)))
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    widget = MainWindow(tmp_path / "appdata", settings)
    widget.messages = messages
    widget.show()
    app.processEvents()
    yield widget
    if widget.busy:
        widget.cancel_event.set()
        wait_until(app, lambda: not widget.busy)
    widget.close()
    app.processEvents()


def test_preview_rename_undo(app, window, make_entry):
    entry = make_entry("photo.JPG")
    window.rules = [RuleSpec("insert", options={"text": "listing_"})]
    window._fill_rules()
    window.add_paths([entry.path])
    wait_until(app, lambda: window.model.plan is not None)
    assert window.rename.isEnabled(), window.progress.text()
    assert Path(entry.path).exists()
    destination = window.model.plan.files[0].destination
    window._rename()
    wait_until(app, lambda: not window.busy)
    assert Path(destination).exists() and not Path(entry.path).exists(), window.messages
    assert window.undo.isEnabled()
    assert window.progress.text() == "Renamed 1 / 1 files · 100%"
    assert not window.rename.isEnabled()  # Never apply an insertion rule twice automatically.
    window._restore()
    wait_until(app, lambda: not window.busy)
    assert Path(entry.path).exists() and not Path(destination).exists(), window.messages
    assert window.model.entries[0].path == entry.path
    assert window.progress.text() == "Restored 1 / 1 files · 100%"
    assert window.model.results[entry.path] == "Restored"


def test_collision_and_exclusion(app, window, make_entry):
    a, b = make_entry("a.txt"), make_entry("b.txt")
    window.rules = [RuleSpec("replace", options={"find": "a", "replacement": "b"})]
    window.add_paths([a.path, b.path])
    wait_until(app, lambda: window.model.plan is not None)
    assert not window.rename.isEnabled()
    assert len(window.model.plan.errors) == 2
    window.model.setData(window.model.index(0, 0), Qt.Unchecked.value, Qt.CheckStateRole)
    wait_until(app, lambda: window.model.plan is not None)
    assert not window.model.plan.errors


def test_stale_preview_and_numbering_order(app, window, make_entry):
    entries = [make_entry(name) for name in ("z.txt", "a.txt")]
    window.rules = [RuleSpec("number")]
    window.add_paths([entry.path for entry in entries])
    wait_until(app, lambda: window.model.plan is not None)
    window._sort(1)
    window.rules = [RuleSpec("insert", options={"text": "latest_"})]
    window._schedule_preview()
    wait_until(app, lambda: window.model.plan is not None)
    assert window.model.plan.revision == window.revision
    assert window.model.plan.files[0].destination.endswith("latest_a.txt")


def test_drop_files(app, window, make_entry):
    entry = make_entry("drop.txt")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(entry.path)])
    enter = QDragEnterEvent(QPoint(30, 30), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.dragEnterEvent(enter)
    assert enter.isAccepted()
    drop = QDropEvent(QPointF(30, 30), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.dropEvent(drop)
    wait_until(app, lambda: window.model.plan is not None)
    assert window.model.entries[0].path == entry.path


def test_regex_timeout_keeps_ui_responsive(app, window, make_entry):
    entry = make_entry("a" * 80 + "!.txt")
    window.rules = [RuleSpec("regex", options={"pattern": "(a+)+$", "replacement": "x"})]
    beats = []
    timer = QTimer()
    timer.setInterval(30)
    timer.timeout.connect(lambda: beats.append(1))
    timer.start()
    window.add_paths([entry.path])
    wait_until(app, lambda: "exceeded its time limit" in window.progress.text(), timeout=12)
    timer.stop()
    assert len(beats) > 50
    assert Path(entry.path).exists()
    assert not window.rename.isEnabled()
    window.rules = [RuleSpec("case")]
    window._schedule_preview()
    wait_until(app, lambda: window.model.plan is not None)


@pytest.mark.parametrize("kind", list(RULE_DEFAULTS))
def test_rule_dialog_roundtrip(app, window, kind):
    rule = RuleSpec(kind, "name" if kind == "repair" else "stem", options=dict(RULE_DEFAULTS[kind]))
    dialog = RuleDialog(window, rule)
    dialog._accept()
    assert dialog.result_rule == rule
    dialog.close()


def test_resizable_and_presets(app, window):
    assert window.minimumSize() != window.maximumSize()
    window.rules = [RuleSpec("case", options={"mode": "upper"})]
    window.presets.save("Uppercase", window.rules)
    window._fill_presets("Uppercase")
    window.rules = []
    window._load_preset("Uppercase")
    assert window.rules[0].options["mode"] == "upper"


def test_real_checkbox_click(app, window, make_entry):
    window.add_paths([make_entry("a.txt").path])
    wait_until(app, lambda: window.model.plan is not None)
    rectangle = window.table.visualRect(window.model.index(0, 0))
    QTest.mouseClick(window.table.viewport(), Qt.LeftButton, pos=rectangle.center())
    assert not window.model.entries[0].included


@pytest.mark.parametrize("width", [720, 960, 1800])
def test_fixed_action_row(app, window, width):
    window.resize(width, 720)
    app.processEvents()
    controls = [window.collapse_rules, window.rule_buttons[0], window.preset_more, window.rename, window.undo]
    positions = [widget.mapTo(window, QPoint()) for widget in controls]
    assert abs(window.rename.geometry().center().x() - window.action_row.rect().center().x()) <= 1
    assert window.undo.x() - window.rename.geometry().right() >= 11
    assert window.undo.geometry().right() == window.action_row.width() - 1
    assert window.rename.size() == window.undo.size()
    assert window.rename.font().pointSizeF() == window.undo.font().pointSizeF()
    assert not hasattr(window, "save_preset_button")
    assert window.preset_more.text() == "Preset"
    assert not hasattr(window, "preset_combo")
    assert window.preset_more.isVisible()
    left_controls = [widget for widget in (window.collapse_rules, *window.rule_buttons,
                                          window.preset_more)
                     if widget.isVisible()]
    for left, right in zip(left_controls, left_controls[1:]):
        assert left.geometry().right() < right.x()
    assert all(abs(widget.mapTo(window, widget.rect().center()).y()
                   - window.rename.mapTo(window, window.rename.rect().center()).y()) <= 1
               for widget in left_controls)
    assert window.rule_controls.geometry().right() + 11 < window.rename.x()
    if width == 1800:
        assert all(button.isVisible() for button in window.rule_buttons)
    for _ in range(2):
        QTest.mouseClick(window.collapse_rules, Qt.LeftButton)
        app.processEvents()
        assert positions == [widget.mapTo(window, QPoint()) for widget in controls]
    assert window.collapse_rules.text() == "Rules"
    assert window.rename.text() == "RENAME"
    assert window.undo.text() == "UNDO"
    assert not hasattr(window, "cancel")


def test_column_menu_and_persistence(app, tmp_path):
    settings = QSettings(str(tmp_path / "columns.ini"), QSettings.IniFormat)
    first = MainWindow(tmp_path / "data", settings)
    first.table.setColumnWidth(0, 82)
    menu = first._make_column_menu()
    menu.actions()[0].trigger()
    assert first.table.isColumnHidden(0)
    assert not menu.actions()[1].isEnabled()
    first.close()
    second = MainWindow(tmp_path / "data", settings)
    assert second.table.isColumnHidden(0)
    second.table.setColumnHidden(0, False)
    assert second.table.columnWidth(0) == 82
    second._make_column_menu().actions()[-1].trigger()
    assert second.table.columnWidth(0) == 70
    assert all(not second.table.isColumnHidden(index) for index in range(3))
    second.close()


@pytest.mark.parametrize("saved", ['bad json', '[]', '{"widths": [0, -1, "x", 2, 3]}'])
def test_invalid_column_settings_use_defaults(app, tmp_path, saved):
    settings = QSettings(str(tmp_path / "columns.ini"), QSettings.IniFormat)
    settings.setValue("file_columns_v2", saved)
    widget = MainWindow(tmp_path / "data", settings)
    assert widget.table.columnWidth(0) == 70
    assert not widget.table.isColumnHidden(1)
    widget.close()


def test_stacked_names_wrap_and_keep_file_selection(app, window, make_entry):
    from file_renamer.planner import build_plan

    entry = make_entry("long-name-" * 16 + ".txt")
    entries = [entry]
    window.model.reset_entries(entries)
    window.model.show_plan(build_plan(entries, [RuleSpec("insert", options={"text": "new-prefix-"})]))
    window.resize(720, 720)
    app.processEvents()
    window.table.resizeRowsToContents()
    index = window.model.index(0, 1)
    original, new = index.data(Qt.UserRole)
    assert original == Path(entry.path).name
    assert new == "new-prefix-" + original
    assert index.data(Qt.ToolTipRole) is None
    narrow_height = window.table.rowHeight(0)
    assert narrow_height > window.table.fontMetrics().height() * 4
    window.table.selectRow(0)
    assert [i.row() for i in window.table.selectionModel().selectedRows()] == [0]
    window.resize(1800, 720)
    app.processEvents()
    window.table.resizeRowsToContents()
    assert window.table.rowHeight(0) < narrow_height
    assert window.model.rowCount() == 1


def test_window_geometry_and_maximize_restore(app, tmp_path):
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.IniFormat)
    first = MainWindow(tmp_path / "data", settings)
    assert first.windowFlags() & Qt.WindowMaximizeButtonHint
    first.show()
    first.resize(740, 670)
    first.move(24, 30)
    app.processEvents()
    normal = first.geometry()
    normal_frame = first.frameGeometry()
    first.close()
    second = MainWindow(tmp_path / "data", settings)
    second.show()
    app.processEvents()
    assert second.size() == normal.size()
    if second.screen().availableGeometry().contains(normal_frame):
        assert second.geometry() == normal
    else:
        # Qt brings a restored window extending off-screen back toward the edge.
        assert second.geometry().y() == normal.y()
        assert second.screen().availableGeometry().left() <= second.x() <= normal.x()
    second.showMaximized()
    app.processEvents()
    second.close()
    third = MainWindow(tmp_path / "data", settings)
    third.show()
    app.processEvents()
    assert third.isMaximized()
    third.showNormal()
    app.processEvents()
    if normal.width() <= third.screen().availableGeometry().width():
        assert third.size() == normal.size()
    else:
        assert third.width() >= third.minimumWidth()
        assert third.height() >= third.minimumHeight()
    third.close()


def test_rule_list_selection_and_definitions(app, window):
    dialog = RuleDialog(window)
    dialog.show()
    app.processEvents()
    from file_renamer.registry import REGISTRY
    assert dialog.kind.count() == len(REGISTRY) + 1
    assert dialog._kind() == "insert"
    assert [dialog.kind.item(i).text() for i in range(dialog.kind.count())] == [
        "Insert", "Delete", "Remove", "Replace", "Rearrange", "Extension", "Strip",
        "Case", "Serialize", "Randomize", "Padding", "Clean Up", "Translit", "Reformat Date", "Regular Expressions",
        "Pascal Script", "User Input", "Mapping",
        "Repair filename",
    ]
    for index in range(dialog.kind.count()):
        item = dialog.kind.item(index)
        kind = item.data(Qt.UserRole)
        if kind is None:
            continue
        dialog.kind.setCurrentRow(index)
        assert set(dialog.widgets) == set(REGISTRY[kind].defaults if kind in REGISTRY else RULE_DEFAULTS[kind])
    dialog.kind.setFocus()
    QTest.keyClick(dialog.kind, Qt.Key_Home)
    assert dialog._kind() == "insert"
    QTest.keyClick(dialog.kind, Qt.Key_Down)
    assert dialog._kind() == "delete"
    QTest.keyClick(dialog.kind, Qt.Key_End)
    assert dialog._kind() == "repair"
    dialog.close()


def test_preset_menu_selection_and_edit_keeps_identity(app, window):
    window.presets.save("Uppercase", [RuleSpec("case", options={"mode": "upper"})])
    window.presets.save("alpha", [RuleSpec("insert", options={"text": "a"})])
    menu = window._make_preset_menu()
    load = menu.actions()[0].menu()
    assert [action.data() for action in load.actions()] == ["alpha", "Uppercase"]
    load.setActiveAction(load.actions()[1])
    load.popup(window.preset_more.mapToGlobal(QPoint()))
    app.processEvents()
    QTest.keyClick(load, Qt.Key_Return)
    assert window.rules[0].options["mode"] == "upper"
    assert window.selected_preset == "Uppercase"
    menu = window._make_preset_menu()
    assert menu.actions()[0].menu().actions()[0].isChecked()
    assert menu.actions()[-1].isEnabled()
    window.rules = [RuleSpec("case", options={"mode": "lower"})]
    window._rules_changed()
    assert window.selected_preset == "Uppercase"
    assert window.preset_label.text() == "Uppercase (modified)"
    assert window._make_preset_menu().actions()[-1].isEnabled()
    window.rules = list(window.presets.presets["Uppercase"])
    window._rules_changed()
    assert window.preset_label.text() == "Uppercase"
    menu.close()


def test_offscreen_saved_position_is_recovered(app, tmp_path):
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.IniFormat)
    first = MainWindow(tmp_path / "data", settings)
    first.move(-20000, -20000)
    first.close()
    second = MainWindow(tmp_path / "data", settings)
    second.show()
    app.processEvents()
    assert any(screen.availableGeometry().contains(second.frameGeometry().topLeft()) for screen in app.screens())
    second.close()


@pytest.mark.parametrize("operation", ["Renaming", "Restoring"])
def test_progress_counts_completed_files(window, operation):
    window.operation = operation
    window._progress(1, 6)
    assert window.progress.text() == "Preparing 1 / 3 files · 0%"
    window._progress(3, 6)
    assert window.progress.text() == "Preparing 3 / 3 files · 0%"
    assert window.progress.file_count == 3
    assert window.progress.value() == 0
    window._progress(4, 6)
    assert window.progress.value() == 1
    assert window.progress.text() == f"{operation} 1 / 3 files · 33%"
    window._progress(6, 6)
    window._finish_progress(True)
    label = "Renamed" if operation == "Renaming" else "Restored"
    assert window.progress.text() == f"{label} 3 / 3 files · 100%"
    window._finish_progress(False)
    assert window.progress.value() == 0
    assert "failed" in window.progress.text()


def test_failed_and_empty_tasks_stop_indeterminate_progress(app, window):
    from file_renamer.models import OperationResult

    def fail(_):
        raise OSError("Cannot access folder")

    window._run_task(fail, lambda result: None)
    assert window.progress.maximum() == 0
    wait_until(app, lambda: not window.busy)
    assert window.progress.maximum() == 100
    assert "failed" in window.progress.text()
    window._run_task(lambda _: OperationResult(False, "No filenames need to change."),
                     window._renamed, "Renaming")
    wait_until(app, lambda: not window.busy)
    assert "failed" in window.progress.text()
    assert "No filenames need to change." in window.progress.text()


def test_close_while_busy_keeps_window_open(app, window):
    from PySide6.QtGui import QCloseEvent

    window._set_busy(True)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert "Cancel" not in window.progress.text()
    window._set_busy(False)


@pytest.mark.parametrize("suffix", [".toml", ".json"])
def test_preset_menu_save_export_import(window, tmp_path, monkeypatch, suffix):
    from PySide6.QtCore import QStandardPaths
    from PySide6.QtWidgets import QDialog, QFileDialog, QMenu

    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda *_: str(tmp_path))

    from file_renamer.rules import RULE_DEFAULTS

    rules = [RuleSpec("insert", options=RULE_DEFAULTS["insert"] | {"text": "saved_"}),
             RuleSpec("case", enabled=False, options=RULE_DEFAULTS["case"])]
    window.rules = rules
    def save(dialog):
        dialog.name.setText("Example")
        return QDialog.Accepted

    monkeypatch.setattr("file_renamer.gui.SavePresetDialog.exec", save)
    chosen = ["Save"]

    def choose(menu, *_):
        assert [action.text() for action in menu.actions() if not action.isSeparator()] == [
            "Load", "Save", "Import", "Export", "Delete"]
        return next(action for action in menu.actions() if action.text() == chosen[0])

    class PresetTestMenu(QMenu):
        def exec(self, *args):
            action = choose(self, *args)
            action.trigger()
            return action

    monkeypatch.setattr("file_renamer.gui.QMenu", PresetTestMenu)
    window._preset_menu()
    assert window.presets.presets["Example"] == rules
    destination = tmp_path / ("export" + suffix)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))
    chosen[0] = "Export"
    window._preset_menu()
    assert destination.exists()
    window.rules = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(destination), ""))
    chosen[0] = "Import"
    window._preset_menu()
    assert window.rules == rules
    assert len(window.presets.presets) == 2
    assert not window.rules[1].enabled
    assert window.rule_list.columnCount() == 3
    assert "Name:" in window.rule_list.item(0, 2).text()


def test_sort_stacked_names_by_destination(app, window, make_entry):
    from file_renamer.planner import build_plan

    entries = [make_entry("a.txt"), make_entry("b.txt")]
    window.rules = [RuleSpec("replace", options={"find": "a", "replacement": "z"})]
    window.model.reset_entries(entries)
    window.model.show_plan(build_plan(entries, window.rules))
    window._sort(1, new_name=True)
    assert Path(window.model.entries[0].path).name == "b.txt"
    wait_until(app, lambda: window.model.plan is not None)
    window._sort(1)
    assert Path(window.model.entries[0].path).name == "a.txt"
    wait_until(app, lambda: window.model.plan is not None)


def test_progress_large_batch_is_file_based(window):
    window.operation = "Renaming"
    window._progress(15000, 20000)
    assert window.progress.file_count == 10000
    assert window.progress.value() == 5000
    assert window.progress.text() == "Renaming 5,000 / 10,000 files · 50%"
    assert not window.progress.grab().isNull()


def test_legacy_column_layout_is_not_reused(app, tmp_path):
    settings = QSettings(str(tmp_path / "legacy.ini"), QSettings.IniFormat)
    settings.setValue("file_columns", '{"widths": [48, 230, 250, 225, 130], "hidden": [2, 3]}')
    settings.setValue("rule_columns", '{"widths": [75, 175, 115, 345]}')
    window = MainWindow(tmp_path / "data", settings)
    assert window.model.HEADERS == ("State", "Name", "Status")
    assert all(not window.table.isColumnHidden(index) for index in range(4))
    assert window.rule_list.columnCount() == 3
    window.close()


def test_filename_delegate_preserves_literal_text(app, window):
    from PySide6.QtWidgets import QStyleOptionViewItem

    from file_renamer.models import FileEntry, FileIdentity

    name = "a  & <b>.txt"
    window.model.reset_entries([FileEntry(str(Path.cwd() / name), FileIdentity(0, 0, 0, 0))])
    index = window.model.index(0, 1)
    option = QStyleOptionViewItem()
    option.font = window.table.font()
    option.rect = window.table.visualRect(index)
    document = window.table.itemDelegateForColumn(1).document(index, option)
    assert document.toPlainText() == f"{name}\n—"
    assert index.data(Qt.AccessibleTextRole) == f"Original: {name}\nNew: —"


def test_preview_segments_follow_changed_included_files(app, window, make_entry):
    entries = [make_entry(name) for name in ("a.txt", "another.txt", "b.txt")]
    window.rules = [RuleSpec("replace", options={"find": "a", "replacement": "z"})]
    window.add_paths([entry.path for entry in entries])
    wait_until(app, lambda: window.model.plan is not None)
    assert window.progress.file_count == 2
    assert window.progress.value() == 0
    assert "2 ready to rename" in window.progress.text()
    window.model.setData(window.model.index(0, 0), Qt.Unchecked.value, Qt.CheckStateRole)
    assert window.progress.file_count == 0
    wait_until(app, lambda: window.model.plan is not None)
    assert window.progress.file_count == 1
    window._rename()
    assert window.progress.file_count == 1
    wait_until(app, lambda: not window.busy)
    assert window.progress.file_count == 1 and window.progress.value() == 1
    window._restore()
    wait_until(app, lambda: not window.busy)
    assert window.progress.file_count == 1 and window.progress.value() == 1
    window._clear()
    assert window.progress.file_count == 0
    assert window.progress.text() == "Ready"
    assert not hasattr(window, "status")
    window.rules = []
    window.add_paths([entries[0].path])
    wait_until(app, lambda: window.model.plan is not None)
    assert window.progress.file_count == 0
    assert "0 ready to rename" in window.progress.text()


def test_compact_rows_and_wrapped_status(app, window, make_entry):
    from PySide6.QtWidgets import QStyleOptionViewItem

    from file_renamer.models import PlannedFile, RenamePlan

    entry = make_entry("deep-folder-" * 10 + "/short.txt")
    window.model.reset_entries([entry])
    window.model.show_plan(RenamePlan(1, (PlannedFile(entry, entry.path),)))
    app.processEvents()
    window._resize_file_rows()
    assert not window.table.wordWrap()
    assert window.table.rowHeight(0) <= window.table.fontMetrics().height() * 2 + 12
    width = window.table.columnWidth(2)
    assert width >= window.table.fontMetrics().horizontalAdvance("Unchanged") + 17
    error = "Destination already exists: please choose another filename"
    window.model.show_plan(RenamePlan(2, (PlannedFile(entry, entry.path, error),)))
    window._resize_file_rows()
    assert window.table.columnWidth(2) >= max(
        window.table.fontMetrics().horizontalAdvance(word) + 17 for word in error.split())
    index = window.model.index(0, 2)
    option = QStyleOptionViewItem()
    option.font = window.table.font()
    option.rect = window.table.visualRect(index)
    document = window.table.itemDelegateForColumn(2).document(index, option)
    assert document.toPlainText() == error
    assert window.table.rowHeight(0) >= document.size().height() + 8
    window.model.reset_entries([])
    window._resize_file_rows()
    assert window.table.columnWidth(2) == window.table.horizontalHeader().fontMetrics().horizontalAdvance("Status") + 20


def test_status_width_ignores_saved_width(app, tmp_path):
    settings = QSettings(str(tmp_path / "status-width.ini"), QSettings.IniFormat)
    settings.setValue("file_columns_v2", '{"widths": [70, 450, 900, 220], "hidden": []}')
    widget = MainWindow(tmp_path / "data", settings)
    assert widget.table.columnWidth(2) < 200
    assert widget.table.model().columnCount() == 3
    widget.close()


def test_removed_labels_and_empty_status_gap(app, window):
    from PySide6.QtWidgets import QLabel

    assert not hasattr(window, "count") and not hasattr(window, "empty")
    assert not hasattr(window, "preset_combo")
    assert "Drop files or folders here" not in [label.text() for label in window.findChildren(QLabel)]
    assert not hasattr(window, "status")
    app.processEvents()
    table_bottom = window.table.mapTo(window, window.table.rect().bottomLeft()).y()
    progress_top = window.progress.mapTo(window, QPoint()).y()
    assert not hasattr(window, "content_scroll")
    assert progress_top - table_bottom <= 14
    window._set_status("A useful message")
    assert window.progress.text() == "A useful message"
    window._set_status("")
    assert window.progress.text() == "Ready"


def test_preset_delete_and_unavailable_library(window, monkeypatch):
    from PySide6.QtWidgets import QDialog

    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.Accepted)
    window.presets.save("A & B", [RuleSpec("case")])
    window._load_preset("A & B")
    menu = window._make_preset_menu()
    assert menu.actions()[0].menu().actions()[0].data() == "A & B"
    menu.actions()[-1].trigger()
    assert not window.presets.presets and not window.selected_preset
    assert window.rules == [RuleSpec("case")]
    window.presets = None
    menu = window._make_preset_menu()
    actions = {action.text(): action for action in menu.actions()}
    assert not actions["Load"].isEnabled()
    assert not actions["Save"].isEnabled()
    assert not actions["Import"].isEnabled()
    assert actions["Export"].isEnabled()


def test_progress_paints_preview_segments_and_plain_idle(window):
    bar = window.progress
    bar.preview(3, "3 files to rename")
    segments = bar.segments()
    assert len(segments) == 3
    assert all(fraction == 0 for _, fraction in segments)
    assert segments[1][0].left() - segments[0][0].right() == pytest.approx(2)
    bar.setValue(1)
    assert [fraction for _, fraction in bar.segments()] == [1, 0, 0]
    assert not bar.grab().isNull()
    bar.preview()
    assert bar.segments() == []


def test_state_square_center_keyboard_and_lock(app, window, make_entry):
    from PySide6.QtCore import QRectF
    from PySide6.QtWidgets import QStyleOptionViewItem

    window.add_paths([make_entry("toggle.txt").path])
    wait_until(app, lambda: window.model.plan is not None)
    index = window.model.index(0, 0)
    option = QStyleOptionViewItem()
    option.initFrom(window.table)
    option.rect = window.table.visualRect(index)
    delegate = window.table.itemDelegateForColumn(0)
    square = delegate.indicator_rect(option)
    assert square.center() == QRectF(option.rect).center()
    pixels = window.table.viewport().grab().toImage()
    ratio = pixels.devicePixelRatio()
    assert pixels.pixelColor(round(square.center().x() * ratio),
                             round((square.top() + 3) * ratio)).rgba() == option.palette.highlight().color().rgba()
    window.table.setCurrentIndex(index)
    window.table.setFocus()
    QTest.keyClick(window.table, Qt.Key_Space)
    assert not window.model.entries[0].included
    assert index.data(Qt.CheckStateRole) == Qt.Unchecked
    wait_until(app, lambda: window.model.plan is not None)
    QTest.mouseClick(window.table.viewport(), Qt.LeftButton, pos=option.rect.center())
    assert window.model.entries[0].included
    wait_until(app, lambda: window.model.plan is not None)
    window._set_busy(True)
    QTest.keyClick(window.table, Qt.Key_Space)
    QTest.mouseClick(window.table.viewport(), Qt.LeftButton, pos=option.rect.center())
    assert window.model.entries[0].included
    window._set_busy(False)


def test_dialog_fits_labels_categories_and_screen(app, window, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QRect

    dialog = RuleDialog(window)
    screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1200))
    monkeypatch.setattr(dialog, "screen", lambda: screen)
    dialog.show()
    dialog._fit_dialog()
    app.processEvents()
    assert dialog.kind.verticalScrollBar().maximum() == 0
    longest = max(dialog.kind.fontMetrics().horizontalAdvance(dialog.kind.item(i).text())
                  for i in range(dialog.kind.count()))
    assert longest + 20 <= dialog.kind.width() <= longest + 40
    for i in range(dialog.kind.count()):
        item = dialog.kind.item(i)
        if item.data(Qt.UserRole) is None:
            assert not item.flags() & Qt.ItemIsSelectable
            continue
        dialog.kind.setCurrentRow(i)
        app.processEvents()
        assert dialog.width() <= 1880
        assert dialog.height() <= 1120
        wait_until(app, lambda: dialog.editor_scroll.verticalScrollBar().maximum() == 0)
    screen.availableGeometry = lambda: QRect(0, 0, 800, 500)
    dialog._fit_dialog()
    app.processEvents()
    assert dialog.height() <= 420
    assert dialog.kind.verticalScrollBar().maximum() > 0
    assert dialog.width() <= 760
    dialog.close()


def test_window_minimum_preserves_all_buttons_on_narrow_screens(app, window, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QRect

    screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(window, "screen", lambda: screen)
    window._update_layout_constraints()
    window.resize(100, 800)
    app.processEvents()
    assert window.width() >= window.content_root.minimumWidth()
    assert not hasattr(window, "rule_more")
    assert all(button.isVisible() for button in window.rule_buttons)
    assert window.rule_buttons[0].text() == "Add Rule"
    for button in [window.collapse_rules, *window.rule_buttons, window.preset_more]:
        assert button.width() >= button.sizeHint().width()
        assert button.mapTo(window.rule_controls, button.rect().topRight()).x() < window.rule_controls.width()
    required = window.content_root.minimumWidth()
    stylesheet = window.styleSheet()
    window.setStyleSheet(stylesheet + "\nQPushButton { font-size: 16pt; }")
    app.processEvents()
    window._update_layout_constraints()
    assert window.content_root.minimumWidth() > required
    for button in window.rule_buttons:
        assert button.width() >= button.sizeHint().width()
    window.setStyleSheet(stylesheet)
    screen.availableGeometry = lambda: QRect(0, 0, 800, 600)
    window._update_layout_constraints()
    window.resize(764, 520)
    app.processEvents()
    assert window.minimumWidth() == window.content_root.minimumWidth()
    assert window.width() >= window.content_root.minimumWidth()
    assert not hasattr(window, "content_scroll")
    for button in [window.collapse_rules, *window.rule_buttons, window.preset_more]:
        assert button.width() >= button.sizeHint().width()
        assert button.mapTo(window.rule_controls, button.rect().topRight()).x() < window.rule_controls.width()
    assert window.undo.mapTo(window, window.undo.rect().topRight()).x() < window.width()
    assert window.progress.width() <= window.width() - 32


def test_centered_status_and_long_message_keep_fixed_bar(window):
    bar = window.progress
    bar.preview(3)
    window._set_status("3 ready to rename · 0 unchanged · 0 errors")
    assert bar.text().startswith("3 ready to rename")
    height, minimum = bar.height(), window.minimumWidth()
    message = "Recovery required:\n" + "very long error detail " * 100
    window._set_status(message)
    assert bar.text() == message and bar.toolTip() == message
    assert bar.accessibleDescription() == message
    assert bar.height() == height and window.minimumWidth() == minimum
    assert height >= 56
    window.operation = "Renaming"
    window._progress(4, 6)
    assert bar.text() == "Renaming 1 / 3 files · 33%"
    window._finish_progress(False)
    assert "failed" in bar.text()
    assert not hasattr(window, "status")


def test_recovery_status_takes_priority_over_preview_summary(app, window, make_entry):
    window.model.reset_entries([make_entry("recover.txt")])
    window.rules = [RuleSpec("case", options={"mode": "upper"})]
    window.recovery_required = True
    window._schedule_preview()
    wait_until(app, lambda: window.model.plan is not None)
    assert window.progress.text().startswith("Recovery required")
    assert not window.rename.isEnabled()


@pytest.mark.parametrize("count", [1, 20])
def test_loaded_rename_color_and_safe_enablement(app, window, make_entry, count):
    entries = [make_entry(f"photo-{index}.txt") for index in range(count)]
    window.rules = []
    window.add_paths([entry.path for entry in entries])
    wait_until(app, lambda: window.model.plan is not None)
    assert window.rename.property("filesLoaded") is True
    assert not window.rename.isEnabled()
    assert "No filename changes" in window.rename.toolTip()
    window.rules = [RuleSpec("insert", options={"text": "new_"})]
    window._schedule_preview()
    wait_until(app, lambda: window.rename.isEnabled())
    assert window.rename.property("filesLoaded") is True
    window._clear()
    assert window.rename.property("filesLoaded") is False
    assert not window.rename.isEnabled()


@pytest.mark.parametrize("label", ["Skipped", "Unchanged", "Recovery required", "Restored"])
def test_status_words_do_not_split(app, window, make_entry, label):
    from PySide6.QtWidgets import QStyleOptionViewItem

    entry = make_entry("status.txt")
    window.model.reset_entries([entry])
    window.model.results[entry.path] = label
    window._resize_file_rows()
    index = window.model.index(0, 2)
    option = QStyleOptionViewItem()
    option.font = window.table.font()
    option.rect = window.table.visualRect(index)
    document = window.table.itemDelegateForColumn(2).document(index, option)
    document.documentLayout().documentSize()
    block = document.firstBlock()
    layout = block.layout()
    for number in range(layout.lineCount()):
        line = layout.lineAt(number)
        end = line.textStart() + line.textLength()
        assert end == len(label) or label[end - 1].isspace() or label[end].isspace()


def test_legacy_folder_column_migrates(app, tmp_path):
    settings = QSettings(str(tmp_path / "legacy.ini"), QSettings.IniFormat)
    settings.setValue("file_columns_v2", '{"widths": [82, 450, 130, 412], "hidden": [0, 3]}')
    window = MainWindow(tmp_path / "data", settings)
    assert window.table.model().columnCount() == 3
    assert window.table.isColumnHidden(0)
    assert "Folder" not in [action.text() for action in window._make_column_menu().actions()]
    window.table.setColumnHidden(0, False)
    assert window.table.columnWidth(0) == 82
    window.close()
    assert settings.contains("file_columns_v3")


@pytest.mark.parametrize("cancel", [False, True])
def test_save_preset_defaults_to_modified_name(window, monkeypatch, cancel):
    from PySide6.QtWidgets import QDialog

    window.presets.save("My preset", [RuleSpec("case")])
    window._load_preset("My preset")
    window.rules = [RuleSpec("insert", options={"text": "new_"})]
    window._rules_changed()

    def answer(dialog):
        assert dialog.name.text() == "My preset"
        return QDialog.Rejected if cancel else QDialog.Accepted

    monkeypatch.setattr("file_renamer.gui.SavePresetDialog.exec", answer)
    window._save_preset()
    assert window.preset_label.text() == ("My preset (modified)" if cancel else "My preset")
    assert (window.presets.presets["My preset"] == window.rules) is not cancel


@pytest.mark.parametrize("selection,cancel,fail", [("alpha", False, False), ("Zulu", True, False),
                                                   ("Zulu", False, True)])
def test_delete_picker_selection_cancel_and_error(window, monkeypatch, selection, cancel, fail):
    from PySide6.QtWidgets import QDialog, QListWidget

    window.presets.save("Zulu", [RuleSpec("case")])
    window.presets.save("alpha", [RuleSpec("insert")])
    window._load_preset("Zulu")

    def answer(dialog):
        choices = dialog.findChild(QListWidget)
        assert [choices.item(i).text() for i in range(choices.count())] == ["alpha", "Zulu"]
        assert choices.currentItem().text() == "Zulu"
        choices.setCurrentRow(0 if selection == "alpha" else 1)
        return QDialog.Rejected if cancel else QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", answer)
    if fail:
        def denied(name):
            raise OSError("Cannot write")
        monkeypatch.setattr(window.presets, "delete", denied)
    window._delete_preset()
    assert window.selected_preset == "Zulu"
    assert window.rules == [RuleSpec("case")]
    assert (selection in window.presets.presets) == (cancel or fail)
    if fail:
        assert window.messages[-1] == ("Preset error", "Cannot write")


def test_preset_label_long_name_and_small_layout(app, window):
    from PySide6.QtWidgets import QScrollArea

    original_minimum = window.minimumWidth()
    name = ("Long preset " * 10).strip()
    window.presets.save(name, [RuleSpec("case")])
    window._load_preset(name)
    window.resize(764, 520)
    app.processEvents()
    assert window.minimumWidth() == original_minimum
    assert window.preset_label.toolTip() == name
    assert abs(window.preset_label.mapTo(window, window.preset_label.rect().center()).x()
               - window.rect().center().x()) <= 1
    assert not window.findChildren(QScrollArea)
    assert window.progress.geometry().bottom() < window.centralWidget().height()
    for widget in (window.rule_controls, window.action_row, window.splitter):
        assert widget.mapTo(window, widget.rect().bottomRight()).y() < window.height()


def test_delete_without_active_preset_requires_selection(window, monkeypatch):
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidget

    window.presets.save("Saved", [RuleSpec("case")])
    assert window._make_preset_menu().actions()[-1].isEnabled()

    def answer(dialog):
        choices = dialog.findChild(QListWidget)
        buttons = dialog.findChild(QDialogButtonBox)
        delete = next(button for button in buttons.buttons() if button.text() == "Delete")
        assert choices.currentRow() == -1
        assert not delete.isEnabled()
        choices.setCurrentRow(0)
        assert delete.isEnabled()
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", answer)
    window._delete_preset()
    assert not window.presets.presets
    assert not window._make_preset_menu().actions()[-1].isEnabled()


def test_save_failure_preserves_modified_identity(window, monkeypatch):
    from PySide6.QtWidgets import QDialog

    window.presets.save("Saved", [RuleSpec("case")])
    window._load_preset("Saved")
    window.rules = []
    window._rules_changed()
    monkeypatch.setattr("file_renamer.gui.SavePresetDialog.exec", lambda dialog: QDialog.Accepted)

    def denied(*args):
        raise OSError("Cannot write")

    monkeypatch.setattr(window.presets, "save", denied)
    window._save_preset()
    assert window.selected_preset == "Saved"
    assert window.preset_label.text() == "Saved (modified)"
    assert window.presets.presets["Saved"] == [RuleSpec("case")]
    assert window.messages[-1] == ("Could not save preset", "Cannot write")


@pytest.mark.parametrize("state", ["pending", "ready", "error"])
def test_file_rows_have_no_tooltips(window, make_entry, state):
    from file_renamer.models import PlannedFile, RenamePlan

    entry = make_entry("example.txt")
    window.model.reset_entries([entry])
    if state != "pending":
        error = "Destination already exists" if state == "error" else ""
        window.model.show_plan(RenamePlan(1, (PlannedFile(entry, entry.path, error),)))
    for column in range(window.model.columnCount()):
        assert window.model.index(0, column).data(Qt.ToolTipRole) is None
    if state == "error":
        assert window.model.index(0, 2).data(Qt.DisplayRole) == "Destination already exists"


@pytest.mark.parametrize("modified,missing", [(False, False), (True, False), (True, True)])
def test_selected_preset_restores_with_rules(app, tmp_path, modified, missing):
    settings = QSettings(str(tmp_path / "preset-session.ini"), QSettings.IniFormat)
    data = tmp_path / "data"
    first = MainWindow(data, settings)
    first.presets.save("Zulu", [RuleSpec("case")])
    first.presets.save("alpha", [RuleSpec("insert")])
    first._load_preset("Zulu")
    if modified:
        first.rules = [RuleSpec("replace", options={"find": "a", "replacement": "b"})]
        first._rules_changed()
    expected = list(first.rules)
    if missing:
        first.presets.delete("Zulu")
    first.close()
    second = MainWindow(data, settings)
    assert second.rules == expected
    assert second.selected_preset == ("" if missing else "Zulu")
    assert second.preset_label.text() == (
        "No preset selected" if missing else "Zulu (modified)" if modified else "Zulu")
    menu = second._make_preset_menu()
    assert [action.data() for action in menu.load_menu.actions()] == (["alpha"] if missing else ["Zulu", "alpha"])
    second.close()


def test_rule_checkbox_and_state_button_mouse_and_keyboard(app, window):
    from PySide6.QtWidgets import QCheckBox

    window.rules = [RuleSpec("case")]
    window._fill_rules()
    app.processEvents()
    table = window.rule_list
    item = table.item(0, 0)
    index = table.indexFromItem(item)
    assert index.data(Qt.CheckStateRole) == Qt.Checked.value
    QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=table.visualRect(index).center())
    assert not window.rules[0].enabled
    table.setCurrentCell(0, 0)
    table.setFocus()
    QTest.keyClick(table, Qt.Key_Space)
    assert window.rules[0].enabled
    dialog = RuleDialog(window, RuleSpec("strip"))
    dialog.show()
    app.processEvents()
    button = dialog.widgets["digits"]
    button.setFocus()
    QTest.keyClick(button, Qt.Key_Space)
    dialog._accept()
    assert dialog.result_rule.options["digits"]
    assert dialog.findChildren(QCheckBox)
    dialog.close()


def test_rule_areas_fit_width_with_long_content(app, window):
    from PySide6.QtWidgets import QComboBox

    window.rules = [RuleSpec("regex", options={"pattern": "a" * 240, "replacement": "b" * 240})]
    window._fill_rules()
    window.resize(window.minimumWidth(), 700)
    app.processEvents()
    table = window.rule_list
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert table.horizontalScrollBar().maximum() == 0
    assert sum(table.columnWidth(i) for i in range(3)) <= table.viewport().width()
    for kind in RULE_DEFAULTS:
        dialog = RuleDialog(window, RuleSpec(kind, "name" if kind == "repair" else "stem"))
        dialog.show()
        app.processEvents()
        assert dialog.editor_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert dialog.editor_scroll.horizontalScrollBar().maximum() == 0
        assert not dialog.findChildren(QComboBox)
        for widget in dialog.widgets.values():
            if widget.isVisible():
                assert widget.mapTo(dialog.definitions, widget.rect().topRight()).x() < dialog.definitions.width()
        dialog.close()


def test_save_preset_font_and_settings_toggle(app, window):
    from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton

    from file_renamer.dialogs import SavePresetDialog, SettingsDialog

    dialog = SavePresetDialog("Name", window)
    for widget in [dialog.name, *dialog.findChildren(QLabel), *dialog.findChildren(QPushButton)]:
        assert widget.font().pointSizeF() == window.font().pointSizeF()
    settings = SettingsDialog(window.settings, window)
    assert settings.recursive.isCheckable()
    assert not settings.findChildren(QCheckBox)
    dialog.close()
    settings.close()


@pytest.mark.parametrize("kind", list(REGISTRY))
def test_rule_choices_are_exclusive_and_visible(app, window, kind):
    from PySide6.QtWidgets import QCheckBox

    from file_renamer.dialogs import ChoiceGroup

    dialog = RuleDialog(window, RuleSpec(kind, behavior="renamer"))
    dialog.show()
    for widget in dialog.widgets.values():
        if isinstance(widget, QCheckBox):
            widget.setChecked(True)
    for widget in dialog.widgets.values():
        if isinstance(widget, ChoiceGroup):
            for index, value in enumerate(widget.values):
                QTest.mouseClick(widget.group.button(index), Qt.LeftButton)
                app.processEvents()
                assert widget.currentData() == value
                assert sum(button.isChecked() for button in widget.group.buttons()) == 1
                assert all(button.isVisible() for button in widget.group.buttons())
    dialog.close()


def test_insert_inline_values_survive_choice_changes(app, window):
    from PySide6.QtWidgets import QLineEdit

    dialog = RuleDialog(window, RuleSpec("insert", behavior="renamer",
                                       options={"text": "new", "match": "old", "index": 7}))
    dialog.show()
    group = dialog.widgets["position"]
    before = next(w for w in dialog.findChildren(QLineEdit) if w.accessibleName() == "Before text")
    for value in ("before", "after", "index", "prefix", "before"):
        group.setCurrentIndex(group.findData(value))
        app.processEvents()
        assert before.isEnabled() == (value == "before")
        assert dialog.widgets["match"].isEnabled() == (value == "after")
        assert dialog.widgets["index"].isEnabled() == (value == "index")
    before.setText("retained")
    assert dialog.widgets["match"].text() == "retained"
    dialog._accept()
    assert dialog.result_rule.options["match"] == "retained"
    assert dialog.result_rule.options["index"] == 7
    assert dialog.result_rule.options["position"] == "before"
    dialog.close()


@pytest.mark.parametrize("kind", list(REGISTRY))
def test_rule_editor_reflows_on_small_scaled_screen(app, window, monkeypatch, kind):
    from types import SimpleNamespace

    from PySide6.QtCore import QRect

    dialog = RuleDialog(window, RuleSpec(kind, behavior="renamer"))
    monkeypatch.setattr(dialog, "screen", lambda: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 533, 533)))
    dialog.show()
    for _ in range(3):
        app.processEvents()
    assert dialog.width() <= 493
    assert dialog.height() <= 453
    assert dialog.definitions.width() <= dialog.editor_scroll.viewport().width()
    assert dialog.editor_scroll.horizontalScrollBar().maximum() == 0
    dialog.close()


def test_help_uses_current_version_and_rule_syntax(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from file_renamer import __version__

    shown = []
    monkeypatch.setattr(QMessageBox, 'exec', lambda box: shown.append(box.text()))
    window._help()
    assert f'Version {__version__}' in shown[0]
    assert 'New rules use one-based positions' in shown[0]
    assert '$1 inserts the first capture group' in shown[0]
    assert 'Legacy presets keep zero-based positions and Python regex' in shown[0]
