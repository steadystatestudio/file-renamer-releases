"""Rich controls for rule text, mapping tables, metadata, and Pascal compilation."""

import csv
import io
import json
import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .compat_rules import mapping_rows
from .metadata import CATALOG


class PascalHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text):
        styles = [
            (
                r"\b(begin|end|var|const|function|procedure|if|then|else|for|to|downto|do|while|repeat|until|array|of|true|false)\b",
                "#508fdb",
            ),
            (r"'([^']|'')*'", "#b183d0"),
            (r"//.*|\{.*?\}", "#758a65"),
        ]
        for pattern, color in styles:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            for match in re.finditer(pattern, text, re.I):
                self.setFormat(match.start(), len(match[0]), fmt)


class TextEditor(QPlainTextEdit):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText(text)

    def keyPressEvent(self, event):
        if self.property("pascal") and event.key() == Qt.Key_Space and event.modifiers() & Qt.ControlModifier:
            from .pascal import FUNCTION_NAMES

            word = self.textCursor()
            word.select(QTextCursor.WordUnderCursor)
            matches = [name for name in FUNCTION_NAMES if name.casefold().startswith(word.selectedText().casefold())]
            if matches:
                name, okay = QInputDialog.getItem(self, "Complete function", "Function", matches, 0, False)
                if okay:
                    word.insertText(name)
            return
        super().keyPressEvent(event)


class MappingEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Match", "New name"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setWordWrap(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setMinimumHeight(170)
        self.table.itemChanged.connect(lambda *_: self.table.resizeRowsToContents())
        layout.addWidget(self.table)
        add = QPushButton("Add mapping")
        add.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        add.clicked.connect(lambda: self.table.insertRow(self.table.rowCount()))
        layout.addWidget(add)
        remove = QPushButton("Remove selected mapping")
        remove.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        remove.clicked.connect(
            lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None
        )
        layout.addWidget(remove)

    def text(self):
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, col).text() if self.table.item(row, col) else "" for col in range(2)]
            if any(values):
                writer.writerow(values)
        return stream.getvalue()

    def setText(self, text):
        rows = mapping_rows(text)
        self.table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.table.resizeRowsToContents()


def insert_metadata(parent, editor):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Insert meta tag")
    layout = QVBoxLayout(dialog)
    choices = QListWidget()
    choices.addItems(CATALOG)
    layout.addWidget(choices)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    choices.itemDoubleClicked.connect(lambda *_: dialog.accept())
    layout.addWidget(buttons)
    dialog.resize(430, 500)
    if dialog.exec() == QDialog.Accepted and choices.currentItem():
        text = ":" + choices.currentItem().text() + ":"
        if isinstance(editor, QPlainTextEdit):
            editor.insertPlainText(text)
        else:
            editor.insert(text)


def transfer_text(parent, editor, action, mapping=False):
    try:
        if action == "Clear":
            editor.setText("")
        elif action == "Load from clipboard":
            editor.setText(QApplication.clipboard().text())
        elif action == "Save to clipboard":
            QApplication.clipboard().setText(editor.text())
        elif action.startswith("Load"):
            path, _ = QFileDialog.getOpenFileName(parent, action, "", "Text (*.txt *.csv *.pas);;All files (*)")
            if path:
                if Path(path).stat().st_size > 1048576:
                    raise ValueError("Rule data exceeds 1 MiB")
                text = Path(path).read_text(encoding="utf-8-sig")
                if mapping and Path(path).suffix.lower() == ".csv":
                    rows = list(csv.reader(io.StringIO(text)))
                    stream = io.StringIO()
                    csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)
                    text = stream.getvalue()
                editor.setText(text)
        else:
            path, _ = QFileDialog.getSaveFileName(parent, action, "", "Text (*.txt);;CSV (*.csv);;Pascal (*.pas)")
            if path:
                text = editor.text()
                if mapping and Path(path).suffix.lower() == ".csv":
                    stream = io.StringIO()
                    csv.writer(stream, lineterminator="\n").writerows(mapping_rows(text))
                    text = stream.getvalue()
                Path(path).write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        QMessageBox.warning(parent, "Rule data", str(exc))


def script_examples():
    return json.loads((Path(__file__).parent / "assets/script-examples.json").read_text(encoding="utf-8"))


def open_script_repository(parent, editor):
    directory = QFileDialog.getExistingDirectory(parent, "Open script repository")
    if not directory:
        return
    files = sorted(Path(directory).glob("*.pas"))
    if not files:
        QMessageBox.information(parent, "Scripts", "This folder contains no Pascal scripts")
        return
    name, okay = QInputDialog.getItem(parent, "Scripts", "Select script", [path.name for path in files], 0, False)
    if okay:
        path = Path(directory) / name
        try:
            if path.stat().st_size > 1048576:
                raise ValueError("Script exceeds 1 MiB")
            editor.setText(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(parent, "Scripts", str(exc))
