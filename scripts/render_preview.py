"""Generate reproducible screenshots using synthetic files and isolated preferences."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from file_renamer.dialogs import RuleDialog, SavePresetDialog, SettingsDialog
from file_renamer.filesystem import scan_paths
from file_renamer.gui import MainWindow
from file_renamer.models import RuleSpec
from file_renamer.planner import build_plan
from file_renamer.themes import apply_theme


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/screenshots")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="renamer-visual-", dir=output.resolve()) as directory:
        root = Path(directory)
        photos = root / "Listing Photos"
        photos.mkdir()
        for name in ["Blue Jacket__Front.JPG", "Blue Jacket__Back.JPG", "Blue Jacket__Detail.JPG",
                     "Canvas Bag__Front.JPG", "Canvas Bag__Detail.JPG", "Vintage Lamp__Front.JPG"]:
            (photos / name).touch()
        settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
        window = MainWindow(root / "appdata", settings)
        window.rules = [RuleSpec("cleanup", options={"separator": "-"}),
                        RuleSpec("case", "name", options={"mode": "lower"}),
                        RuleSpec("number", options={"width": 3})]
        window._fill_rules(0)
        window.presets.save("Listing photos", window.rules)
        window._fill_presets("Listing photos")
        entries, _ = scan_paths([str(photos)], False)
        window.model.reset_entries(entries)
        window.model.show_plan(build_plan(entries, window.rules))
        window.rename.setEnabled(True)
        window.progress.preview(6, "6 files to rename")
        window._set_status("6 ready to rename  ·  0 unchanged  ·  0 errors")
        window.show()
        for theme in ("dark", "light"):
            apply_theme(app, theme)
            app.processEvents()
            window._resize_file_rows()
            window.grab().save(str(output / f"{theme}.png"))
        # Also inspect the intended full layout independent of the offscreen platform's 800px screen.
        window.resize(960, 860)
        window.splitter.setSizes([290, 430])
        for theme in ("dark", "light"):
            apply_theme(app, theme)
            app.processEvents()
            window._resize_file_rows()
            window.grab().save(str(output / f"{theme}-full.png"))
        window._toggle_rules_panel()
        app.processEvents()
        window.grab().save(str(output / "collapsed.png"))
        window._toggle_rules_panel()
        window.resize(720, 650)
        app.processEvents()
        window.grab().save(str(output / "small.png"))
        window.resize(1800, 1000)
        app.processEvents()
        window.grab().save(str(output / "wide.png"))
        window.resize(960, 860)
        window.operation = "Renaming"
        window._progress(9, 12)
        app.processEvents()
        window.grab().save(str(output / "progress.png"))
        for theme in ("dark", "light"):
            apply_theme(app, theme)
            dialog = RuleDialog(window, RuleSpec("insert", options={"text": "listing_"}))
            dialog.show()
            app.processEvents()
            app.processEvents()
            dialog.grab().save(str(output / f"rule-editor-{theme}.png"))
            dialog.close()
            for kind in ("replace", "number", "strip", "cleanup"):
                dialog = RuleDialog(window, RuleSpec(kind))
                dialog.show()
                app.processEvents()
                app.processEvents()
                dialog.grab().save(str(output / f"rule-{kind}-{theme}.png"))
                dialog.close()
            for name, dialog in (("save-preset", SavePresetDialog("Listing photos", window)),
                                 ("settings", SettingsDialog(settings, window))):
                dialog.show()
                app.processEvents()
                app.processEvents()
                dialog.grab().save(str(output / f"{name}-{theme}.png"))
                dialog.close()
        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
