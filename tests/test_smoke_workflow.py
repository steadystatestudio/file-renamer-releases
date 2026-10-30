import json
import os
import subprocess
import sys


def test_source_smoke_renames_and_restores_synthetic_files(tmp_path):
    root = tmp_path / "workflow"
    result = subprocess.run(
        [sys.executable, "-m", "file_renamer", "--smoke-workflow", str(root)],
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((root / "result.json").read_text(encoding="utf-8"))
    assert receipt["files"] == 3
    assert receipt["rename"] == receipt["undo"] == "passed"
    assert receipt["hashes_before"] == receipt["hashes_after"]
    assert not (root / "application.lock").exists()


def test_diagnostic_refuses_existing_destination(tmp_path):
    marker = tmp_path / "important.txt"
    marker.write_bytes(b"preserve")
    result = subprocess.run(
        [sys.executable, "-m", "file_renamer", "--smoke-workflow", str(tmp_path)],
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert marker.read_bytes() == b"preserve"
    assert set(tmp_path.iterdir()) == {marker}
