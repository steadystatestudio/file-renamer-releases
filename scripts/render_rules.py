"""Render each expanded editor using isolated app preferences."""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from file_renamer.dialogs import RuleDialog
from file_renamer.gui import MainWindow
from file_renamer.models import RuleSpec
from file_renamer.registry import REGISTRY
from file_renamer.themes import apply_theme


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/rule-editors")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rule-render-") as temp:
        root = Path(temp)
        window = MainWindow(root / "data", QSettings(str(root / "settings.ini"), QSettings.IniFormat))
        for theme in ("dark", "light"):
            apply_theme(app, theme)
            for kind in REGISTRY:
                dialog = RuleDialog(window, RuleSpec(kind, behavior="renamer"))
                dialog.show()
                app.processEvents()
                app.processEvents()
                dialog.grab().save(str(output / f"{theme}-{kind}.png"))
                dialog.close()
        window.close()
    print(f"Rendered all 18 editors: {output}")


if __name__ == "__main__":
    main()
