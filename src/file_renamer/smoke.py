"""Exercise the real packaged preview, rename and Undo on synthetic files only."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .models import RuleSpec


def run(app, window, root: Path) -> None:
    inputs = root / "inputs"
    inputs.mkdir(exist_ok=False)
    originals = {
        "blue_jacket.JPG": b"synthetic blue jacket\n",
        "café_02.txt": b"synthetic unicode filename\n",
        "photo_10.png": b"synthetic third file\n",
    }
    for name, content in originals.items():
        (inputs / name).write_bytes(content)
    before = {name: hashlib.sha256(content).hexdigest() for name, content in originals.items()}
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

    window.rules = [RuleSpec("insert", behavior="renamer", options={"text": "listing_"})]
    window._fill_rules()
    window.add_paths([str(inputs / name) for name in originals])
    drain(lambda: not window.busy and window.model.plan is not None)
    assert window.rename.isEnabled(), window.progress.text()
    assert len(window.model.plan.changes) == len(originals)
    for row in window.model.plan.files:
        assert Path(row.destination).name == "listing_" + Path(row.entry.path).name
    assert window.grab().save(str(root / "ui-preview.png"))
    window.rename.click()
    drain(lambda: not window.busy)
    for name, content in originals.items():
        assert not (inputs / name).exists()
        assert (inputs / ("listing_" + name)).read_bytes() == content
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
    (root / "result.json").write_text(json.dumps({
        "success": True, "files": len(originals), "preview": "passed",
        "rename": "passed", "undo": "passed", "originals_unchanged": True,
        "hashes_before": before, "hashes_after": after,
    }, indent=2) + "\n", encoding="utf-8")
