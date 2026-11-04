from __future__ import annotations

import sys
from pathlib import Path


def _isolated_data_directory(argument: str) -> Path:
    from .filesystem import linked

    # Check the original path before resolve can hide a dangling link or junction.
    path = Path(argument).absolute()
    for part in (path, *path.parents):
        try:
            if linked(part):
                raise ValueError("Links and junctions are not allowed in an isolated data path")
        except FileNotFoundError:
            pass
    return path.resolve()


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--preview-worker":
        from .worker import main as worker_main
        return worker_main(sys.argv[2], sys.argv[3])

    isolated_mode = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in {
        "--smoke-ui", "--smoke-workflow", "--qa-ui"
    } else None
    if isolated_mode and len(sys.argv) != 3:
        print(f"Usage: File-Renamer {isolated_mode} FRESH_DIRECTORY", file=sys.stderr)
        return 2

    from PySide6.QtCore import QLockFile, QSettings, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import __version__
    from .application_paths import application_data_dir, configure_application
    from .gui import MainWindow

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app = QApplication(sys.argv)
    from .system_fonts import capture_system_appearance
    capture_system_appearance(app)
    configure_application(app, __version__)
    app.setStyle("Fusion")
    # Isolated modes accept a fresh destination only; never use ordinary user data.
    try:
        isolated_dir = _isolated_data_directory(sys.argv[2]) if isolated_mode else None
        data_dir = isolated_dir or application_data_dir()
        data_dir.mkdir(parents=True, exist_ok=isolated_dir is None)
    except (OSError, ValueError) as exc:
        if isolated_mode is None:
            raise
        print(f"Choose a fresh, writable directory for {isolated_mode}: {exc}", file=sys.stderr)
        return 2
    lock = QLockFile(str(data_dir / "application.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        # Construct the first widget through Python before entering a modal loop.
        # PySide's static information() helper releases the GIL while Qt creates
        # the dialog, which can crash its first Python meta-object lookup.
        notice = QMessageBox(
            QMessageBox.Information, "File Renamer",
            "File Renamer is already open, or its data folder is locked.",
            QMessageBox.Ok,
        )
        notice.exec()
        return 1
    settings = QSettings(str(isolated_dir / "settings.ini"), QSettings.IniFormat) if isolated_dir else None
    if settings is not None:
        settings.setFallbacksEnabled(False)
    window = MainWindow(data_dir, settings)
    if isolated_mode == "--qa-ui":
        window.setWindowTitle("File Renamer — Isolated QA")
    app.styleHints().colorSchemeChanged.connect(
        lambda _: _refresh_theme(app, window)
    )
    window.show()
    if isolated_mode in {"--smoke-ui", "--smoke-workflow"}:
        def finish_smoke():
            try:
                if isolated_mode == "--smoke-workflow":
                    from .smoke import run
                    run(app, window, isolated_dir)
                else:
                    assert window.grab().save(str(isolated_dir / "ui.png"))
            except Exception:
                import traceback
                (isolated_dir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                app.exit(1)
            else:
                window.close()
        QTimer.singleShot(300, finish_smoke)
    code = app.exec()
    lock.unlock()
    return code


def _refresh_theme(app, window):
    from .themes import apply_theme
    apply_theme(app, window.settings.value("theme", "system", type=str))
