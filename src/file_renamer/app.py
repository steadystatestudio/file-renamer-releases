from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--preview-worker":
        from .worker import main as worker_main
        return worker_main(sys.argv[2], sys.argv[3])

    from PySide6.QtCore import QLockFile, QSettings, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import __version__
    from .application_paths import application_data_dir, configure_application
    from .gui import MainWindow

    app = QApplication(sys.argv)
    configure_application(app, __version__)
    app.setStyle("Fusion")
    # Private packaging diagnostic: render the actual bundled GUI in isolated storage and exit.
    smoke_dir = Path(sys.argv[2]).resolve() if len(sys.argv) == 3 and sys.argv[1] == "--smoke-ui" else None
    data_dir = smoke_dir or application_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(data_dir / "application.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "File Renamer", "File Renamer is already open, or its data folder is locked.")
        return 1
    settings = QSettings(str(smoke_dir / "settings.ini"), QSettings.IniFormat) if smoke_dir else None
    window = MainWindow(data_dir, settings)
    app.styleHints().colorSchemeChanged.connect(
        lambda _: _refresh_theme(app, window)
    )
    window.show()
    if smoke_dir:
        def finish_smoke():
            window.grab().save(str(smoke_dir / "ui.png"))
            window.close()
        QTimer.singleShot(300, finish_smoke)
    code = app.exec()
    lock.unlock()
    return code


def _refresh_theme(app, window):
    from .themes import apply_theme
    apply_theme(app, window.settings.value("theme", "system", type=str))
