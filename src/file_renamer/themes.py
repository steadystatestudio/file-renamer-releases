"""Canonical Steady State Studio desktop colors and control styling."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from .system_fonts import apply_system_font, system_font_css


def apply_theme(app: QApplication, preference: str = "system") -> None:
    apply_system_font(app)
    # Qt's offscreen Windows plugin may enumerate no fonts. Register an installed
    # desktop font for QA rendering without replacing the desktop font settings.
    if app.platformName() == "offscreen" and os.name == "nt" and not QFontDatabase.families():
        font_file = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
        if font_file.is_file():
            QFontDatabase.addApplicationFont(str(font_file))
    dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    if preference == "system" and os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                dark = winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        except OSError:
            pass
    if preference != "system":
        dark = preference == "dark"
    background, panel, field = ("#2c2c2c", "#252525", "#303030") if dark else ("#f3f3f3", "#ffffff", "#fafafa")
    text, muted, border = ("#f1f1f1", "#b5b5b5", "#555555") if dark else ("#222222", "#626262", "#cccccc")
    selection = "#508fdb"
    app.setProperty("dark", dark)
    palette = QPalette()
    from PySide6.QtGui import QColor
    for role, color in [(QPalette.Window, background), (QPalette.WindowText, text),
                        (QPalette.Base, field), (QPalette.Text, text),
                        (QPalette.AlternateBase, "#4a4a4a" if dark else "#e2e2e2"),
                        (QPalette.Mid, border), (QPalette.Button, panel),
                        (QPalette.ButtonText, text), (QPalette.Highlight, selection),
                        (QPalette.HighlightedText, "#111111"), (QPalette.ToolTipBase, panel),
                        (QPalette.ToolTipText, text)]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(f"""
        QWidget {{ color: {text}; {system_font_css(app)} }}
        QMainWindow, QDialog {{ background: {background}; }}
        QPushButton {{ background: transparent; border: 1px solid {border}; border-radius: 6px;
                       padding: 9px 13px; min-height: 19px; }}
        QPushButton:hover {{ background: {field}; border-color: {selection}; }}
        QPushButton:pressed, QPushButton:checked {{ background: {selection}; color: #111111; }}
        QPushButton:disabled {{ color: {muted}; border-color: {border}; }}
        QPushButton:focus, QComboBox:focus, QLineEdit:focus {{ border: 2px solid {selection}; }}
        QPushButton#primary {{ background: #2768ad; color: white; font-weight: 600;
                               border: 1px solid #2768ad; }}
        QPushButton#primary:hover:!disabled {{ background: #2f6db1; }}
        QPushButton#primary:pressed:!disabled {{ background: #2463a6; }}
        QPushButton#primary:disabled {{ background: {border}; color: {muted}; }}
        QPushButton#primary[filesLoaded="true"]:disabled {{ background: #2768ad; color: #d5e3f5; }}
        QFrame#panel {{ background: {panel}; border: 1px solid {border}; border-radius: 10px; }}
        QTableView, QListWidget {{ background: {panel}; border: 1px solid {border}; border-radius: 8px;
                                 selection-background-color: {selection}; gridline-color: {border}; }}
        QTableView::item, QListWidget::item {{ padding: 7px; }}
        QTableView#fileTable::item {{ padding: 3px 8px; }}
        QHeaderView::section {{ background: {field}; color: {muted}; padding: 9px 8px;
                               border: none; border-bottom: 1px solid {border}; }}
        QLineEdit, QComboBox, QSpinBox {{ background: {field}; border: 1px solid {border};
                                       border-radius: 6px; padding: 7px; min-height: 21px; }}
        QComboBox QAbstractItemView {{ background: {panel}; selection-background-color: {selection}; }}

        QComboBox QAbstractItemView::item, QMenu::item {{ min-height: 26px; padding: 6px 10px; }}
        QWidget#actionRow QPushButton {{ padding: 7px 9px; }}
        QDialog#ruleDialog QPushButton {{ padding: 4px 9px; min-height: 19px; }}
        QDialog#ruleDialog QLineEdit, QDialog#ruleDialog QSpinBox {{ padding: 3px; min-height: 21px; }}
        QDialog#ruleDialog QRadioButton, QDialog#ruleDialog QCheckBox {{ spacing: 6px; }}
        QDialog#ruleDialog QListWidget::item {{ padding: 2px 6px; }}
        QDialog#ruleDialog QLabel#sectionHeading {{ padding-top: 3px; }}
        QLabel#muted {{ color: {muted}; }}
        QLabel#heading {{ font-weight: 600; }}
        QLabel#sectionHeading {{ font-weight: 600; padding-top: 8px; }}
        QProgressBar {{ border: none; border-radius: 6px; background: {panel};
                       text-align: center; min-height: 36px; padding: 10px 32px;
                       font-weight: 600; }}
        QToolTip {{ background: {panel}; color: {text}; border: 1px solid {border}; padding: 6px; }}
    """)
