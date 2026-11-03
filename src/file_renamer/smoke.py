"""Exercise the real packaged preview, rename and Undo on synthetic files only."""
from __future__ import annotations

import hashlib
import json
import struct
import time
from pathlib import Path


def tiff_fixture() -> bytes:
    """A real 2×3 uncompressed grayscale TIFF, without a host image dependency."""
    model = b"StudioQA\0"
    model_offset = 8 + 2 + 10 * 12 + 4
    pixels_offset = model_offset + len(model) + 1
    fields = [(256, 4, 1, 2), (257, 4, 1, 3), (258, 3, 1, 8), (259, 3, 1, 1),
              (262, 3, 1, 1), (272, 2, len(model), model_offset), (273, 4, 1, pixels_offset),
              (277, 3, 1, 1), (278, 4, 1, 3), (279, 4, 1, 6)]
    return (struct.pack("<2sHIH", b"II", 42, 8, len(fields))
            + b"".join(struct.pack("<HHII", *field) for field in fields)
            + struct.pack("<I", 0) + model + b"\0" + bytes([0, 50, 100, 150, 200, 255]))


def run(app, window, root: Path) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton

    from .dialogs import RuleDialog
    from .metadata import Metadata
    from .rules import RULE_ORDER

    inputs = root / "inputs"
    inputs.mkdir(exist_ok=False)
    originals = {
        "blue_jacket.JPG": b"synthetic blue jacket\n",
        "café_02.txt": b"synthetic unicode filename\n",
        "photo_10.tif": tiff_fixture(),
    }
    for name, content in originals.items():
        (inputs / name).write_bytes(content)
    before = {name: hashlib.sha256(content).hexdigest() for name, content in originals.items()}
    metadata = Metadata()
    tiff = str(inputs / "photo_10.tif")
    assert metadata.get("Image_Width", tiff) == "2"
    assert metadata.get("Image_Height", tiff) == "3"
    assert metadata.get("TIFF_Model", tiff) == "StudioQA"
    messages = []
    window._message = lambda title, message: messages.append((title, message))

    def drain(predicate):
        deadline = time.monotonic() + 30
        while not predicate():
            app.processEvents()
            if messages:
                raise RuntimeError(f"Workflow failed: {messages}")
            if time.monotonic() > deadline:
                raise RuntimeError("Packaged workflow timed out")
            time.sleep(.005)
        app.processEvents()
        if messages:
            raise RuntimeError(f"Workflow failed: {messages}")

    def button(parent, label):
        matches = [widget for widget in parent.findChildren(QPushButton)
                   if widget.text() == label and widget.isVisible()]
        assert len(matches) == 1, f"Expected one {label} control"
        return matches[0]

    def rule_dialog(action, kind, options, save_label):
        errors = []

        def fill_editor():
            dialog = app.activeModalWidget()
            original_warning = QMessageBox.warning
            try:
                assert isinstance(dialog, RuleDialog), "Rule editor did not open"
                # Capture a rejected rule rather than leaving its warning modal open.
                QMessageBox.warning = lambda parent, title, message: errors.append(f"{title}: {message}")
                if kind is not None:
                    dialog.kind.setCurrentRow(RULE_ORDER.index(kind))
                for key, value in options.items():
                    dialog.widgets[key].setText(value)
                button(dialog, save_label).click()
                assert dialog.result() == QDialog.Accepted, "The editor rejected the new rule"
            except Exception as exc:
                errors.append(str(exc))
            finally:
                QMessageBox.warning = original_warning
                if dialog and dialog.isVisible():
                    dialog.reject()

        QTimer.singleShot(0, fill_editor)
        button(window, action).click()
        if errors:
            raise RuntimeError(f"Packaged rule editor failed: {errors}")

    # Go through MainWindow's real Add Rule/Edit controls and modal acceptance.
    # Direct RuleSpec injection would miss the unset target bug in first-time creation.
    rule_dialog("Add Rule", "insert", {"text": "draft_"}, "Add Rule")
    assert len(window.rules) == 1
    rule_dialog("Edit", None, {"text": "listing_"}, "Save Rule")
    assert window.rules[0].options["text"] == "listing_"
    rule_dialog("Add Rule", "replace", {"find": "listing_", "replacement": "ready_"}, "Add Rule")
    assert [rule.kind for rule in window.rules] == ["insert", "replace"]
    window.add_paths([str(inputs / name) for name in originals])
    drain(lambda: not window.busy and window.model.plan is not None)
    assert window.rename.isEnabled(), window.progress.text()
    assert len(window.model.plan.changes) == len(originals)
    for row in window.model.plan.files:
        assert Path(row.destination).name == "ready_" + Path(row.entry.path).name
    assert window.grab().save(str(root / "ui-preview.png"))
    window.rename.click()
    drain(lambda: not window.busy)
    for name, content in originals.items():
        assert not (inputs / name).exists()
        assert (inputs / ("ready_" + name)).read_bytes() == content
    assert window.undo.isEnabled()
    assert not window.rename.isEnabled()
    assert window.manager.load()["status"] == "committed"
    window.undo.click()
    drain(lambda: not window.busy)
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs.iterdir()}
    assert before == after
    assert window.manager.load()["status"] == "undone"
    assert not list(inputs.glob(".file-renamer-*.tmp"))
    assert window.grab().save(str(root / "ui.png"))
    # The exact frozen application must also preserve apostrophes through its
    # real Case editor, preview worker, filesystem operation and recovery path.
    window._clear()
    window.rules = []
    window._fill_rules()
    case_inputs = root / "case-inputs"
    case_inputs.mkdir()
    case_names = {"it's alice’s file.txt": "It's Alice’s File.txt", "don't stop.txt": "Don't Stop.txt"}
    for name in case_names:
        (case_inputs / name).write_bytes(b"apostrophe regression input")
    rule_dialog("Add Rule", "case", {}, "Add Rule")
    window.add_paths([str(case_inputs / name) for name in case_names])
    drain(lambda: not window.busy and window.model.plan is not None)
    assert window.rename.isEnabled(), window.progress.text()
    for row in window.model.plan.files:
        assert Path(row.destination).name == case_names[Path(row.entry.path).name]
    window.rename.click()
    drain(lambda: not window.busy)
    for name in case_names.values():
        assert (case_inputs / name).read_bytes() == b"apostrophe regression input"
    window.undo.click()
    drain(lambda: not window.busy)
    assert set(path.name for path in case_inputs.iterdir()) == set(case_names)
    assert all(path.read_bytes() == b"apostrophe regression input" for path in case_inputs.iterdir())
    (root / "result.json").write_text(json.dumps({
        "success": True, "files": len(originals), "preview": "passed",
        "rename": "passed", "undo": "passed", "originals_unchanged": True,
        "rule_creation": "passed", "rule_editing": "passed", "created_rule_kinds": ["insert", "replace"],
        "tiff_metadata": "passed", "tiff_original_unchanged": after["photo_10.tif"] == before["photo_10.tif"],
        "hashes_before": before, "hashes_after": after,
        "case_apostrophes_preview_rename_undo": "passed",
    }, indent=2) + "\n", encoding="utf-8")
