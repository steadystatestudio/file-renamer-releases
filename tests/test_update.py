import os
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QStandardPaths, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog

from file_renamer.filename_policy import filename_error, repair_filename
from file_renamer.filesystem import name_error
from file_renamer.gui import FileTableModel, MainWindow, visible_text
from file_renamer.models import FileEntry, FileIdentity, RuleSpec
from file_renamer.planner import build_plan
from file_renamer.rules import RULE_DEFAULTS, apply_rule, split_name
from file_renamer.storage import backup_preset, restore_preset
from file_renamer.transactions import TransactionManager


@pytest.mark.parametrize("kind,options,source,result", [
    ("insert", {"position": "before", "match": "X", "text": "!", "occurrence": "last"}, "aXaX.txt", "aXa!X.txt"),
    ("insert", {"position": "after", "match": "x", "text": "!", "case_sensitive": False}, "aX.txt", "aX!.txt"),
    ("insert", {"position": "after", "match": "missing", "text": "!"}, "a.txt", "a.txt"),
    ("delete", {"start": 1, "count": 2, "from_right": True}, "abcde.txt", "abe.txt"),
    ("delete", {"start": 20, "count": 2, "from_right": True}, "abc.txt", "abc.txt"),
    ("delete", {"mode": "before", "delimiter": "_"}, "one_two.txt", "_two.txt"),
    ("delete", {"mode": "after", "delimiter": "_", "include_delimiters": True}, "one_two.txt", "one.txt"),
    ("delete", {"mode": "between", "delimiter": "[", "end_delimiter": "]"}, "a[x]b.txt", "a[]b.txt"),
    ("delete", {"mode": "between", "delimiter": "[", "end_delimiter": "]", "include_delimiters": True},
     "a[x]b.txt", "ab.txt"),
    ("delete", {"mode": "between", "delimiter": "[", "end_delimiter": "]"}, "a[x.txt", "a[x.txt"),
    ("replace", {"find": "aa", "replacement": "X", "occurrence": "last"}, "aaaaa.txt", "aaXa.txt"),
    ("replace", {"find": "a", "replacement": "X", "occurrence": "first", "all": True}, "aaa.txt", "Xaa.txt"),
    ("replace", {"find": "a", "replacement": "X", "occurrence": "all", "all": False}, "aaa.txt", "XXX.txt"),
    ("remove", {"text": "A", "case_sensitive": False, "occurrence": "last"}, "aAa.txt", "aA.txt"),
    ("strip", {"digits": True, "symbols": True}, "a١2★.txt", "a.txt"),
    ("strip", {"punctuation": True, "whitespace": True, "characters": "x"}, "a— x_b.txt", "ab.txt"),
    ("accents", {}, "café_Å_Ελλάδα_猫.txt", "cafe_A_Ελλάδα_猫.txt"),
    ("rearrange", {"delimiter": "_", "template": "{3}-{1}-{1}-{{ok}}"}, "a__c.txt", "c-a-a-{ok}.txt"),
    ("repair", {"platform": "Windows-compatible"}, "CON.txt", "_CON.txt"),
    ("repair", {"platform": "Windows-compatible"}, "a?b.txt. ", "a_b.txt"),
])
def test_new_rules(kind, options, source, result):
    assert apply_rule(source, RuleSpec(kind, options=options), 0) == result


@pytest.mark.parametrize("template", ["{0}", "{3}", "{1.foo}", "{1!r}", "{1:03}", "{"])
def test_rearrange_invalid_parts(template):
    with pytest.raises(ValueError):
        apply_rule("a_b.txt", RuleSpec("rearrange", options={"template": template}), 0)


def test_extension_split_is_filename_only():
    assert split_name(r"a.b\c.txt") == (r"a.b\c", "txt")
    assert split_name(".config") == (".config", "")
    assert split_name("archive.tar.gz") == ("archive.tar", "gz")
    assert split_name("trailing.") == ("trailing.", "")


@pytest.mark.parametrize("name", ["a\\b.txt", "a:b?.txt", "CON", "trailing. ", "line\nname"])
def test_linux_policy_preserves_valid_characters(name):
    assert not filename_error(name, windows=False)
    assert repair_filename(name, windows=False) == name
    assert filename_error(name, windows=True)
    assert not filename_error(repair_filename(name, windows=True), windows=True)


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\0b"])
def test_common_invalid_names(name):
    for windows in (False, True):
        assert filename_error(name, windows)
        assert not filename_error(repair_filename(name, windows), windows)


def test_visible_controls():
    assert visible_text("a\nb\tc") == r"a\u000ab\u0009c"
    model = FileTableModel()
    model.reset_entries([FileEntry(str(Path.cwd() / "a\nb.txt"), FileIdentity(0, 0, 0, 0))])
    assert model.data(model.index(0, 1), Qt.UserRole)[0] == r"a\u000ab.txt"
    assert model.data(model.index(0, 1), Qt.ToolTipRole) is None
    assert r"a\u000ab.txt" in model.data(model.index(0, 1), Qt.AccessibleTextRole)


@pytest.mark.parametrize("suffix", [".toml", ".json"])
def test_all_rules_backup_roundtrip(tmp_path, suffix):
    rules = [RuleSpec(kind, options=dict(options)) for kind, options in RULE_DEFAULTS.items()]
    rules += [RuleSpec("insert", enabled=False, options={"text": "猫_\"\\\n"}),
              RuleSpec("regex", options={"pattern": r"(\d+)", "replacement": r"\g<1>"})]
    path = tmp_path / ("preset" + suffix)
    backup_preset(path, "猫 Photos", rules)
    name, restored = restore_preset(path)
    assert name == "猫 Photos"
    assert [(r.kind, r.enabled, r.target, RULE_DEFAULTS[r.kind] | r.options) for r in restored] == [
        (r.kind, r.enabled, r.target, RULE_DEFAULTS[r.kind] | r.options) for r in rules]
    assert "猫" in path.read_text(encoding="utf-8")


def test_edited_toml_and_legacy_json(tmp_path):
    path = tmp_path / "edited.toml"
    path.write_text('version = 1\nname = "Edited"\n[[rules]]\nkind = "replace"\n'
                    '[rules.options]\nfind = "a"\nreplacement = "b"\nall = false\n', encoding="utf-8")
    _, rules = restore_preset(path)
    assert apply_rule("aaa.txt", rules[0], 0) == "baa.txt"
    json_path = tmp_path / "old.json"
    json_path.write_text('{"version":1,"name":"Old","rules":[{"kind":"case"}]}', encoding="utf-8")
    assert restore_preset(json_path)[1] == [RuleSpec("case")]


def test_backup_write_failure_preserves_previous(tmp_path, monkeypatch):
    path = tmp_path / "preset.toml"
    backup_preset(path, "Original", [RuleSpec("case")])
    before = path.read_bytes()
    def fail(*args):
        raise PermissionError("read only")
    monkeypatch.setattr("file_renamer.storage.os.replace", fail)
    with pytest.raises(PermissionError):
        backup_preset(path, "Changed", [RuleSpec("accents")])
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".renamer-*"))


def test_layout_and_restore_state(app, tmp_path):
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    window = MainWindow(tmp_path / "data", settings)
    window.show()
    window.resize(1000, 800)
    window.splitter.setSizes([300, 400])
    app.processEvents()
    assert window.rules_panel.y() < window.table.mapTo(window.splitter, window.table.rect().topLeft()).y()
    assert window.table.showGrid() and window.rule_list.showGrid()
    assert not window.rule_list.isSortingEnabled()
    original = window.splitter.sizes()[0]
    QTest.mouseClick(window.collapse_rules, Qt.LeftButton)
    app.processEvents()
    assert window.rule_body.isHidden() and window.preset_more.isVisible()
    assert window.splitter.sizes()[0] < original
    QTest.mouseClick(window.collapse_rules, Qt.LeftButton)
    app.processEvents()
    assert abs(window.splitter.sizes()[0] - original) < 5
    window._toggle_rules_panel()
    window.close()
    second = MainWindow(tmp_path / "data", settings)
    assert second.rules_collapsed and second.rule_body.isHidden()
    assert second.rules_height == original
    second.close()


def test_backup_dialog_and_restore_failures(app, tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    window = MainWindow(tmp_path / "data", settings)
    messages = []
    window._message = lambda *args: messages.append(args)
    window.rules = [RuleSpec("case")]
    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda location: str(
        tmp_path / "missing" if location == QStandardPaths.DocumentsLocation else tmp_path))
    captured = []
    def choose(*args):
        captured.append(args)
        return str(tmp_path / "chosen"), "JSON preset (*.json)"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    window._backup_preset()
    assert Path(captured[0][2]).parent == tmp_path
    assert (tmp_path / "chosen.json").exists()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(tmp_path / "chosen.json"), ""))
    window._restore_preset()
    window._restore_preset()
    assert set(window.presets.presets) == {"My rules", "My rules (2)"}
    previous = dict(window.presets.presets)
    (tmp_path / "chosen.json").write_text('{"version":999}', encoding="utf-8")
    window._restore_preset()
    assert window.presets.presets == previous and messages
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("", ""))
    window._backup_preset()
    assert window.presets.presets == previous
    window.close()


@pytest.mark.skipif(os.name == "nt", reason="Linux filename and transaction behavior")
def test_linux_backslash_rename_and_undo(make_entry, tmp_path):
    entry = make_entry("a.txt")
    plan = build_plan([entry], [RuleSpec("insert", options={"text": "valid\\:"})])
    assert not plan.errors
    manager = TransactionManager(tmp_path / "journal.json")
    result = manager.execute(plan)
    assert result.success
    assert Path(plan.files[0].destination).exists()
    assert manager.restore().success
    assert Path(entry.path).exists()


def test_repair_collision_and_disabled_rule(make_entry):
    a, b = make_entry("a.txt"), make_entry("b.txt")
    rules = [RuleSpec("regex", options={"pattern": ".*", "replacement": "CON", "all": False}),
             RuleSpec("repair", options={"platform": "Windows-compatible"})]
    assert len(build_plan([a, b], rules).errors) == 2
    assert apply_rule("a.txt", replace(rules[1], enabled=False), 0) == "a.txt"


def test_unicode_filename_length(tmp_path):
    # Emoji consume four UTF-8 bytes on Linux and two UTF-16 units on Windows.
    count = 128 if os.name == "nt" else 64
    assert name_error(tmp_path / ("😀" * count))
    assert not name_error(tmp_path / ("😀" * (count - 1)))


@pytest.mark.skipif(os.name == "nt", reason="POSIX pathconf")
def test_linux_filesystem_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "pathconf", lambda path, key: 10 if key == "PC_NAME_MAX" else 4096)
    assert name_error(tmp_path / "éééééé")
    assert not name_error(tmp_path / "ééééé")
    monkeypatch.setattr(os, "pathconf", lambda path, key: 255 if key == "PC_NAME_MAX" else 5)
    assert "Path exceeds" in name_error(tmp_path / "a")


@pytest.mark.skipif(os.name != "nt", reason="Windows volume query")
def test_windows_volume_limits_and_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("file_renamer.filesystem.windows_name_limit", lambda parent: calls.append(parent) or 10)
    limits = {}
    assert name_error(tmp_path / ("x" * 11), limits)
    assert not name_error(tmp_path / ("x" * 10), limits)
    assert len(calls) == 1
