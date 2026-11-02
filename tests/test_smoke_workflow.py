import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


def source_environment():
    # pytest's pythonpath setting does not reach subprocesses. CI also installs a
    # wheel before building native helpers into src, so test this checkout explicitly.
    source = Path(__file__).resolve().parents[1] / "src"
    return dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(source))


def test_source_smoke_renames_and_restores_synthetic_files(tmp_path):
    root = tmp_path / "workflow"
    result = subprocess.run(
        [sys.executable, "-m", "file_renamer", "--smoke-workflow", str(root)],
        env=source_environment(), capture_output=True, text=True, timeout=120,
    )
    error = root / "error.txt"
    diagnostic = error.read_text(encoding="utf-8") if error.exists() else result.stdout + result.stderr
    assert result.returncode == 0, diagnostic
    receipt = json.loads((root / "result.json").read_text(encoding="utf-8"))
    assert receipt["files"] == 3
    assert receipt["rename"] == receipt["undo"] == "passed"
    assert receipt["rule_creation"] == receipt["rule_editing"] == "passed"
    assert receipt["created_rule_kinds"] == ["insert", "replace"]
    assert receipt["tiff_metadata"] == "passed" and receipt["tiff_original_unchanged"]
    assert receipt["hashes_before"] == receipt["hashes_after"]
    assert not (root / "application.lock").exists()


@pytest.mark.parametrize("mode", ["--smoke-workflow", "--smoke-ui", "--qa-ui"])
def test_diagnostic_refuses_existing_destination(tmp_path, mode):
    marker = tmp_path / "important.txt"
    marker.write_bytes(b"preserve")
    result = subprocess.run(
        [sys.executable, "-m", "file_renamer", mode, str(tmp_path)],
        env=source_environment(), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert marker.read_bytes() == b"preserve"
    assert set(tmp_path.iterdir()) == {marker}


@pytest.mark.parametrize("extra", [[], ["unused", "extra"]])
def test_qa_mode_requires_exactly_one_directory(extra):
    result = subprocess.run(
        [sys.executable, "-m", "file_renamer", "--qa-ui", *extra],
        env=source_environment(), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert "FRESH_DIRECTORY" in result.stderr


def test_qa_mode_runs_normal_event_loop_with_isolated_empty_state(tmp_path):
    root = tmp_path / "interactive"
    probe = r'''
import json
from pathlib import Path
import sys
from PySide6.QtCore import QTimer
from file_renamer import app, application_paths, gui

def forbidden():
    raise AssertionError("Ordinary application settings/data were requested")

application_paths.application_data_dir = forbidden
gui.application_settings = forbidden
original_window = gui.MainWindow

class ObservedWindow(original_window):
    def __init__(self, data_dir, settings):
        super().__init__(data_dir, settings)
        def observe():
            (data_dir / "observation.json").write_text(json.dumps({
                "data_dir": str(data_dir), "settings_file": settings.fileName(),
                "fallbacks": settings.fallbacksEnabled(), "rules": len(self.rules),
                "files": len(self.model.entries), "busy": self.busy,
                "normal_event_loop": True, "title": self.windowTitle(),
            }), encoding="utf-8")
            self.close()
        QTimer.singleShot(50, observe)

gui.MainWindow = ObservedWindow
raise SystemExit(app.main())
'''
    result = subprocess.run(
        [sys.executable, "-c", probe, "--qa-ui", str(root)],
        env=source_environment(), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observation = json.loads((root / "observation.json").read_text(encoding="utf-8"))
    from pathlib import Path
    assert Path(observation["data_dir"]) == root
    assert Path(observation["settings_file"]) == root / "settings.ini"
    assert observation["normal_event_loop"] and not observation["fallbacks"]
    assert observation["rules"] == observation["files"] == 0
    assert not observation["busy"]
    assert observation["title"] == "File Renamer — Isolated QA"
    assert not (root / "application.lock").exists()


def test_duplicate_instance_builds_notice_safely_before_main_window(tmp_path):
    """The first notice must not construct a native widget after releasing the GIL."""
    ready = tmp_path / "owner-ready"
    report = tmp_path / "duplicate-notice.json"
    environment = source_environment() | {
        "RENAMER_TEST_DATA": str(tmp_path / "data"),
        "RENAMER_TEST_NOTICE": str(report),
    }
    owner_probe = r'''
from pathlib import Path
import os
import sys
import time
from PySide6.QtCore import QCoreApplication, QLockFile
from file_renamer import __version__
from file_renamer.application_paths import configure_application
app = QCoreApplication([])
configure_application(app, __version__)
data = Path(os.environ["RENAMER_TEST_DATA"])
data.mkdir(parents=True, exist_ok=True)
lock = QLockFile(str(data / "application.lock"))
assert lock.tryLock(100)
Path(sys.argv[1]).write_text(str(data), encoding="utf-8")
time.sleep(60)
'''
    duplicate_probe = r'''
import json
import os
from pathlib import Path
import sys
from PySide6.QtWidgets import QMessageBox
from file_renamer import application_paths, gui

def forbidden_window(*args, **kwargs):
    raise AssertionError("A duplicate instance must not create the main window")

def acknowledge_notice(self):
    Path(os.environ["RENAMER_TEST_NOTICE"]).write_text(json.dumps({
        "title": self.windowTitle(), "text": self.text(),
        "icon": self.icon().value, "buttons": self.standardButtons().value,
    }), encoding="utf-8")
    return QMessageBox.Ok.value

# Do not create a QTimer or other widget first: that hides the early-dialog crash.
QMessageBox.exec = acknowledge_notice
gui.MainWindow = forbidden_window
application_paths.application_data_dir = lambda: Path(os.environ["RENAMER_TEST_DATA"])
from file_renamer.app import main
sys.argv = [sys.argv[0]]
raise SystemExit(main())
'''
    owner = subprocess.Popen(
        [sys.executable, "-c", owner_probe, str(ready)],
        env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and owner.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "The isolated lock owner did not start"
        duplicate = subprocess.run(
            [sys.executable, "-c", duplicate_probe], env=environment,
            capture_output=True, text=True, timeout=20,
        )
        assert duplicate.returncode == 1, duplicate.stdout + duplicate.stderr
        assert report.exists(), duplicate.stdout + duplicate.stderr
        notice = json.loads(report.read_text(encoding="utf-8"))
        assert notice["title"] == "File Renamer"
        assert "already open" in notice["text"] and "locked" in notice["text"]
        from PySide6.QtWidgets import QMessageBox
        assert notice["icon"] == QMessageBox.Information.value
        assert notice["buttons"] == QMessageBox.Ok.value
        assert owner.poll() is None
        assert (Path(ready.read_text(encoding="utf-8")) / "application.lock").exists()
    finally:
        owner.terminate()
        owner.communicate(timeout=10)


@pytest.mark.parametrize("mode", ["--smoke-workflow", "--smoke-ui", "--qa-ui"])
def test_isolated_modes_reject_dangling_links_without_creating_the_target(tmp_path, mode):
    missing_target = tmp_path / "must-not-be-created"
    link = tmp_path / "existing-link"
    try:
        link.symlink_to(missing_target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Creating symbolic links is unavailable: {exc}")
    result = subprocess.run(
        [sys.executable, "-m", "file_renamer", mode, str(link)],
        env=source_environment(), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2 and "Links and junctions" in result.stderr
    assert link.is_symlink() and not missing_target.exists()


def test_isolated_directory_checks_ancestors_before_resolution(tmp_path, monkeypatch):
    from file_renamer import filesystem
    from file_renamer.app import _isolated_data_directory

    ancestor = tmp_path / "redirected"
    target = ancestor / "fresh"
    checked = []

    def redirected(path):
        checked.append(path)
        return path == ancestor

    monkeypatch.setattr(filesystem, "linked", redirected)
    monkeypatch.setattr(Path, "resolve", lambda *_: pytest.fail("Resolved before rejecting a link"))
    with pytest.raises(ValueError, match="Links and junctions"):
        _isolated_data_directory(str(target))
    assert checked == [target, ancestor]
    assert not target.exists()
