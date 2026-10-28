from __future__ import annotations

import html
import json
import math
import sys
import tempfile
import threading
import unicodedata
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QProcess,
    QRectF,
    QSettings,
    QSize,
    QStandardPaths,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QSplitterHandle,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .application_paths import application_settings
from .dialogs import RuleDialog, SavePresetDialog, SettingsDialog
from .filesystem import path_key, scan_paths
from .models import FileEntry, RenamePlan, RuleSpec
from .rules import RULE_LABELS, rule_details, rule_summary
from .storage import PresetStore, atomic_json, backup_preset, parse_preset, preset_data, read_json, restore_preset
from .themes import apply_theme
from .transactions import TransactionManager

KOFI_URL = "https://ko-fi.com/steadystatestudio"
FILE_COLUMN_WIDTHS = (70, 450, 130)
RULE_COLUMN_WIDTHS = (75, 175, 345)


class PresetLabel(QLabel):
    """Keep long preset names from increasing the window's minimum width."""

    def sizeHint(self):
        return QSize(160, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(40, super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.WindowText))
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        painter.drawText(self.rect(), Qt.AlignCenter, text)


class ActionRow(QWidget):
    """Center Rename independently of the rule controls."""

    def __init__(self, rename, undo, controls):
        super().__init__()
        self.rename, self.undo, self.controls = rename, undo, controls
        for widget in (rename, undo, controls):
            widget.setParent(self)
        self.setObjectName("actionRow")

    def action_width(self):
        return max(112, self.rename.sizeHint().width(), self.undo.sizeHint().width())

    def sizeHint(self):
        return QSize(
            2 * max(self.controls.sizeHint().width(), self.action_width()) + self.action_width() + 24,
            max(48, self.controls.sizeHint().height(), self.rename.sizeHint().height(), self.undo.sizeHint().height())
        )

    def minimumSizeHint(self):
        return self.sizeHint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange()

    def showEvent(self, event):
        super().showEvent(event)
        self.arrange()

    def arrange(self):
        width = self.action_width()
        self.controls.setGeometry(0, 0, self.controls.sizeHint().width(), self.height())
        self.rename.setGeometry((self.width() - width) // 2, 0, width, self.height())
        self.undo.setGeometry(self.width() - width, 0, width, self.height())


class RuleTable(QTableWidget):
    """Fit all columns and wrap statements instead of scrolling sideways."""

    def fit_columns(self):
        available = self.viewport().width()
        self.setColumnWidth(0, min(available // 5, self.fontMetrics().horizontalAdvance("Enable") + 32))
        names = (self.item(row, 1).text() for row in range(self.rowCount()) if self.item(row, 1))
        longest = max(names, key=self.fontMetrics().horizontalAdvance, default="Rule")
        self.setColumnWidth(1, min(available // 3, max(150, self.fontMetrics().horizontalAdvance(longest) + 48)))
        self.resizeRowsToContents()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_columns()


def proposed_name_color():
    return QColor("#83b8f3" if QApplication.instance().property("dark") else "#2464b1")


class StateDelegate(QStyledItemDelegate):
    """A rounded highlight button backed by the model check state."""

    @staticmethod
    def indicator_rect(option):
        rect = QRectF(option.rect).adjusted(8, 5, -8, -5)
        rect.setHeight(min(rect.height(), option.fontMetrics.height() + 14))
        rect.moveCenter(QRectF(option.rect).center())
        return rect

    def paint(self, painter, option, index):
        prepared = QStyleOptionViewItem(option)
        self.initStyleOption(prepared, index)
        prepared.features &= ~QStyleOptionViewItem.HasCheckIndicator
        prepared.text = ""
        style = prepared.widget.style() if prepared.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, prepared, painter, prepared.widget)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if not index.flags() & Qt.ItemIsUserCheckable:
            painter.setOpacity(0.45)
        color = proposed_name_color()
        painter.setPen(QPen(color, 1))
        painter.setBrush(color if index.data(Qt.CheckStateRole) in (Qt.Checked, Qt.Checked.value) else Qt.NoBrush)
        rect = self.indicator_rect(option)
        painter.drawRoundedRect(rect, 5, 5)
        checked = index.data(Qt.CheckStateRole) in (Qt.Checked, Qt.Checked.value)
        painter.setPen(QColor("white") if checked else color)
        painter.drawText(rect, Qt.AlignCenter, "On" if checked else "Off")
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if not index.flags() & Qt.ItemIsUserCheckable or not index.flags() & Qt.ItemIsEnabled:
            return False
        if event.type() == QEvent.MouseButtonDblClick:
            return True
        if event.type() == QEvent.MouseButtonRelease:
            if event.button() != Qt.LeftButton or not self.indicator_rect(option).contains(event.position()):
                return False
        elif event.type() == QEvent.KeyPress:
            if event.key() not in {Qt.Key_Space, Qt.Key_Select}:
                return False
        else:
            return False
        value = Qt.Unchecked if index.data(Qt.CheckStateRole) in (Qt.Checked, Qt.Checked.value) else Qt.Checked
        return model.setData(index, value.value, Qt.CheckStateRole)


def visible_text(value: str) -> str:
    return "".join(f"\\u{ord(c):04x}" if unicodedata.category(c) == "Cc" else c for c in value)


class RulesSplitter(QSplitter):
    def createHandle(self):
        return RulesGrip(self.orientation(), self)


class RulesGrip(QSplitterHandle):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.palette().windowText())
        center = self.rect().center()
        for offset in (-6, 0, 6):
            painter.drawEllipse(center.x() + offset - 1, center.y() - 1, 3, 3)


class TaskThread(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function(self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


class FilenameDelegate(QStyledItemDelegate):
    """Paint both names together, with wrapping measured at the actual column width."""

    def document(self, index, option):
        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setDocumentMargin(0)
        original, new = index.data(Qt.UserRole)
        selected = bool(option.state & QStyle.State_Selected)
        normal = option.palette.color(QPalette.HighlightedText if selected else QPalette.Text).name()
        accent = index.data(Qt.ForegroundRole)
        new_color = normal if selected or accent is None else accent.name()
        if index.data(Qt.UserRole + 1):
            normal = new_color
        document.setHtml(
            f'<span style="color:{normal}; white-space:pre-wrap">{html.escape(original)}</span><br>'
            f'<span style="color:{new_color}; white-space:pre-wrap">{html.escape(new)}</span>'
        )
        document.setTextWidth(max(1, option.rect.width() - 16))
        return document

    def sizeHint(self, option, index):
        measured = QStyleOptionViewItem(option)
        # With word wrapping disabled for Folder, Qt supplies an empty measurement rect.
        measured.rect.setWidth(self.parent().columnWidth(index.column()) - 1)
        return QSize(100, int(self.document(index, measured).size().height()) + 8)

    def paint(self, painter, option, index):
        prepared = QStyleOptionViewItem(option)
        self.initStyleOption(prepared, index)
        prepared.text = ""
        style = prepared.widget.style() if prepared.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, prepared, painter, prepared.widget)
        document = self.document(index, option)
        painter.save()
        painter.setClipRect(option.rect)
        painter.translate(option.rect.left() + 8, option.rect.top() + 4)
        document.drawContents(painter)
        painter.restore()


class StatusDelegate(FilenameDelegate):
    """Wrap complete error text without letting it consume the filename column."""

    def document(self, index, option):
        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setDocumentMargin(0)
        color = (
            option.palette.color(QPalette.HighlightedText)
            if option.state & QStyle.State_Selected
            else index.data(Qt.ForegroundRole) or option.palette.color(QPalette.Text)
        )
        document.setHtml(
            f'<span style="color:{color.name()}; white-space:pre-wrap">{html.escape(index.data(Qt.DisplayRole))}</span>'
        )
        document.setTextWidth(max(1, option.rect.width() - 16))
        return document


class FileProgressBar(QProgressBar):
    """Padder-style rounded segments and a single centered status message."""

    GAP = 2.0
    MIN_SEGMENT_WIDTH = 5.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_count = 0
        self._message = ""

    def set_message(self, text):
        self._message = text
        self.setToolTip(self.text())
        self.setAccessibleDescription(self.text())
        self.update()

    def setFormat(self, text):
        self._message = ""
        super().setFormat(text)
        self.setToolTip(self.text())
        self.setAccessibleDescription(self.text())
        self.update()

    def text(self):
        return self._message or (self.format() if self.maximum() == 0 else super().text())

    def preview(self, count=0, text="Ready"):
        self.file_count = count
        self.setRange(0, max(count, 1))
        self.setValue(0)
        self.setFormat(text)

    def segments(self):
        inner = QRectF(self.rect()).adjusted(4.5, 4.5, -4.5, -4.5)
        if not self.file_count or inner.width() <= 0:
            return []
        count = min(self.file_count, max(1, int((inner.width() + self.GAP) // (self.MIN_SEGMENT_WIDTH + self.GAP))))
        width = (inner.width() - self.GAP * (count - 1)) / count
        files_per_segment = self.file_count / count
        return [
            (
                QRectF(inner.left() + i * (width + self.GAP), inner.top(), width, inner.height()),
                max(0.0, min(1.0, (self.value() - i * files_per_segment) / files_per_segment)),
            )
            for i in range(count)
        ]

    def paintEvent(self, event):
        painter = QPainter(self)
        font = self.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setRenderHint(QPainter.Antialiasing)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(self.palette().mid().color()))
        painter.setBrush(self.palette().base())
        painter.drawRoundedRect(area, 6, 6)
        filled = QPainterPath()
        painter.setPen(Qt.NoPen)
        for rect, fraction in self.segments():
            painter.setBrush(self.palette().alternateBase())
            painter.drawRoundedRect(rect, 2, 2)
            if fraction:
                rect.setWidth(rect.width() * fraction)
                painter.setBrush(self.palette().highlight())
                painter.drawRoundedRect(rect, 2, 2)
                filled.addRoundedRect(rect, 2, 2)
        text_area = area.adjusted(10, 0, -10, 0)
        display_text = " ".join(self.text().splitlines())
        text = QFontMetrics(font).elidedText(display_text, Qt.ElideRight, max(0, int(text_area.width())))
        painter.setPen(self.palette().text().color())
        painter.drawText(text_area, Qt.AlignCenter, text)
        painter.setClipPath(filled)
        painter.setPen(self.palette().highlightedText().color())
        painter.drawText(text_area, Qt.AlignCenter, text)


class FileTableModel(QAbstractTableModel):
    changed = Signal()
    HEADERS = ("State", "Name", "Status")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[FileEntry] = []
        self.plan: RenamePlan | None = None
        self.results: dict[str, str] = {}
        self.locked = False

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def flags(self, index):
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0 and not self.locked:
            flags |= Qt.ItemIsUserCheckable
        return flags

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.entries):
            return None
        entry = self.entries[index.row()]
        planned = self.plan.files[index.row()] if self.plan else None
        column = index.column()
        if role == Qt.CheckStateRole and column == 0:
            return Qt.Checked if entry.included else Qt.Unchecked
        if role == Qt.ForegroundRole:
            if planned and planned.error and entry.included:
                return QColor("#e66c6c" if QApplication.instance().property("dark") else "#ad3030")
            if column == 1 and planned and planned.changed:
                return proposed_name_color()
        if role == Qt.UserRole + 1:
            return bool(planned and planned.error and entry.included)
        if role == Qt.UserRole and column == 1:
            return (
                visible_text(Path(entry.path).name),
                visible_text(Path(planned.destination).name) if planned else "—",
            )
        if role == Qt.AccessibleTextRole and column == 1:
            original, new = self.data(index, Qt.UserRole)
            return f"Original: {original}\nNew: {new}"
        if role == Qt.DisplayRole:
            if column == 1:
                original, new = self.data(index, Qt.UserRole)
                return f"{original}\n{new}"
            status = "Skipped" if not entry.included else self.results.get(entry.path, "Preview pending")
            if planned and entry.included:
                status = planned.error or ("Ready" if planned.changed else "Unchanged")
            return visible_text(("", "", status)[column])
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if index.isValid() and index.column() == 0 and role == Qt.CheckStateRole and not self.locked:
            self.entries[index.row()] = replace(self.entries[index.row()], included=value == Qt.Checked.value)
            self.plan = None
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            self.changed.emit()
            return True
        return False

    def reset_entries(self, entries):
        self.beginResetModel()
        self.entries = entries
        self.plan = None
        self.results = {}
        self.endResetModel()

    def show_plan(self, plan):
        self.plan = plan
        self.refresh()

    def refresh(self):
        if self.entries:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.entries) - 1, self.columnCount() - 1))


class MainWindow(QMainWindow):
    def __init__(self, data_dir: Path, settings: QSettings | None = None):
        super().__init__()
        self.setWindowTitle("File Renamer")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "assets/icon.svg")))
        self.setAcceptDrops(True)
        self.data_dir = data_dir
        self.settings = settings or application_settings()
        self.manager = TransactionManager(data_dir / "last-rename.json")
        self.rules: list[RuleSpec] = []
        self.selected_preset = ""
        self.revision = 0
        self.busy = False
        self.recovery_required = False
        self.process: QProcess | None = None
        self.preview_temp = None
        self.preview_reason = ""
        self.preview_ready = False
        self.task: TaskThread | None = None
        self.cancel_event = threading.Event()
        self.operation = ""
        self.progress_total = 0
        self.startup_errors = []
        try:
            self.presets = PresetStore(data_dir / "presets.json")
        except Exception as exc:
            self.presets = None
            self.startup_errors.append(f"Preset library could not be read and was left intact: {exc}")
        try:
            saved = self.settings.value("rules", "", type=str)
            if saved:
                _, self.rules = parse_preset(json.loads(saved))
        except Exception as exc:
            self.startup_errors.append(f"Saved rules could not be loaded: {exc}")
        apply_theme(QApplication.instance(), self.settings.value("theme", "system", type=str))
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(300)
        self.debounce.timeout.connect(self._launch_preview)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._preview_timeout)
        self.ready_poll = QTimer(self)
        self.ready_poll.setInterval(30)
        self.ready_poll.timeout.connect(self._check_preview_ready)
        self._build_ui()
        self._fill_rules()
        self._fill_presets(self.settings.value("selected_preset", "", type=str))
        self._update_undo()
        QTimer.singleShot(0, self._startup_notice)

    def _button(self, text, callback, tooltip=""):
        button = QPushButton(text)
        button.clicked.connect(callback)
        button.setToolTip(tooltip)
        return button

    def _build_ui(self):
        root = QWidget()
        self.content_root = root
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(root, 1)
        self.setCentralWidget(central)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        toolbar = QGridLayout()
        self.toolbar_layout = toolbar
        self.add_files = self._button("Add Files", self._browse_files, "Choose files to rename · Ctrl+O")
        self.add_folder = self._button("Add Folder", self._browse_folder, "Collect files from a folder")
        self.clear = self._button("Clear", self._clear, "Remove all files from this list")
        self.help_button = self._button("Help", self._help)
        self.donate_button = self._button("Donate", self._open_donate, "Support development on Ko-fi")
        self.settings_button = self._button("Settings", self._settings)
        self.toolbar_left = QWidget()
        left_layout = QHBoxLayout(self.toolbar_left)
        self.toolbar_right = QWidget()
        right_layout = QHBoxLayout(self.toolbar_right)
        for row in (left_layout, right_layout):
            row.setContentsMargins(0, 0, 0, 0)
        for widget in (self.add_files, self.add_folder, self.clear):
            left_layout.addWidget(widget)
        for widget in (self.help_button, self.donate_button, self.settings_button):
            right_layout.addWidget(widget)
        self.preset_label = PresetLabel("No preset selected")
        self.preset_label.setAccessibleName("Current preset")
        toolbar.addWidget(self.toolbar_left, 0, 0, Qt.AlignLeft)
        toolbar.addWidget(self.preset_label, 0, 1)
        toolbar.addWidget(self.toolbar_right, 0, 2, Qt.AlignRight)
        toolbar.setColumnStretch(1, 1)
        layout.addLayout(toolbar)
        files_panel = QWidget()
        files_layout = QVBoxLayout(files_panel)
        files_layout.setContentsMargins(0, 0, 0, 0)
        self.model = FileTableModel(self)
        self.model.changed.connect(self._schedule_preview)
        self.table = QTableView()
        self.table.setObjectName("fileTable")
        self.table.setModel(self.model)
        self.table.setShowGrid(True)
        self.table.setWordWrap(False)
        self.table.setItemDelegateForColumn(0, StateDelegate(self.table))
        self.table.setItemDelegateForColumn(1, FilenameDelegate(self.table))
        self.table.setItemDelegateForColumn(2, StatusDelegate(self.table))
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(39)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for column, width in enumerate(FILE_COLUMN_WIDTHS):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.row_resize_timer = QTimer(self)
        self.row_resize_timer.setSingleShot(True)
        self.row_resize_timer.setInterval(40)
        self.row_resize_timer.timeout.connect(self._resize_file_rows)
        self.table.horizontalHeader().sectionResized.connect(lambda *_: self.row_resize_timer.start())
        self.model.modelReset.connect(lambda: self.row_resize_timer.start())
        self.model.dataChanged.connect(lambda *_: self.row_resize_timer.start())
        self.table.horizontalHeader().sectionClicked.connect(self._sort)
        self.table.horizontalHeader().sectionHandleDoubleClicked.connect(self._fit_column)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self._column_menu)
        self.sort_direction: dict[tuple[int, bool], bool] = {}
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        files_layout.addWidget(self.table, 1)
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        action_left = QWidget()
        self.rule_controls = action_left
        preset_row = QHBoxLayout(action_left)
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(5)
        self.collapse_rules = QPushButton("Rules")
        self.collapse_rules.setCheckable(True)
        self.collapse_rules.setChecked(True)
        self.collapse_rules.clicked.connect(self._toggle_rules_panel)
        self.collapse_rules.setToolTip("Collapse or expand Rules")
        self.collapse_rules.setAccessibleName("Collapse or expand Rules")
        preset_row.addWidget(self.collapse_rules)
        self.preset_more = self._button("Preset", self._preset_menu, "Load, save, import, export or delete presets")
        self.preset_more.setAccessibleName("Preset menu")
        self.rule_body = QWidget()
        body_layout = QVBoxLayout(self.rule_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self.rule_list = RuleTable(0, 3)
        self.rule_list.setItemDelegateForColumn(0, StateDelegate(self.rule_list))
        self.rule_list.setHorizontalHeaderLabels(["Enable", "Rule", "Statement"])
        self.rule_list.setShowGrid(True)
        self.rule_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rule_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.rule_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rule_list.verticalHeader().hide()
        self.rule_list.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate(RULE_COLUMN_WIDTHS):
            self.rule_list.setColumnWidth(column, width)
        self.rule_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.rule_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.rule_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.rule_list.horizontalHeader().sectionResized.connect(lambda *_: self.rule_list.resizeRowsToContents())
        self.rule_list.setWordWrap(True)
        self.rule_list.setTextElideMode(Qt.ElideNone)
        self.rule_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rule_list.setMinimumHeight(90)
        self.rule_list.itemChanged.connect(self._toggle_rule)
        self.rule_list.itemDoubleClicked.connect(lambda _: self._edit_rule())
        body_layout.addWidget(self.rule_list, 1)
        self.rule_buttons = []
        for label, callback in [
            ("Add Rule", self._add_rule),
            ("Edit", self._edit_rule),
            ("Duplicate", self._duplicate_rule),
            ("Remove", self._remove_rule),
            ("↑", lambda: self._move_rule(-1)),
            ("↓", lambda: self._move_rule(1)),
        ]:
            button = self._button(label, callback)
            if label in {"↑", "↓"}:
                button.setAccessibleName("Move rule up" if label == "↑" else "Move rule down")
            button.setToolTip(button.accessibleName() or label)
            preset_row.addWidget(button)
            self.rule_buttons.append(button)
        self.rule_buttons[0].setAccessibleName("Add Rule")
        preset_row.addWidget(self.preset_more)
        preset_row.addStretch()
        self.undo = self._button("UNDO", self._restore, "Undo last rename · Ctrl+Shift+Z")
        self.rename = self._button("RENAME", self._rename, "Rename files · F6")
        self.rename.setObjectName("primary")
        self.model.modelReset.connect(self._update_rename_appearance)
        self.model.dataChanged.connect(self._update_rename_appearance)
        self.rename.setEnabled(False)
        self._update_rename_appearance()
        self.action_row = ActionRow(self.rename, self.undo, action_left)
        layout.addWidget(self.action_row)
        panel_layout.addWidget(self.rule_body, 1)
        self.rules_panel = panel
        self.splitter = RulesSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        self.splitter.addWidget(panel)
        self.splitter.addWidget(files_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        handle = self.splitter.handle(1)
        handle.setCursor(Qt.SplitVCursor)
        handle.setToolTip("Drag to resize Rules")
        layout.addWidget(self.splitter, 1)
        self.progress = FileProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setAccessibleName("File operation progress")
        self.progress.preview()
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(16, 0, 16, 16)
        footer_layout.addWidget(self.progress)
        central_layout.addWidget(footer)
        scale = max(1, self.fontMetrics().height() / 19)
        available = self.screen().availableGeometry()
        self.resize(min(round(960 * scale), available.width() - 36), min(round(860 * scale), available.height() - 65))
        self.move(available.center() - self.rect().center())
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
            if not any(
                screen.availableGeometry().contains(self.frameGeometry().topLeft()) for screen in QApplication.screens()
            ):
                self.move(available.topLeft())
        self.rules_height = self.settings.value("rules_height", 240, type=int)
        self.splitter.setSizes([self.rules_height, 480])
        self.rules_collapsed = False
        if self.settings.value("rules_collapsed", False, type=bool):
            self._toggle_rules_panel()
        self._restore_columns()
        self._resize_file_rows()
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self._update_layout_constraints)
        self._update_layout_constraints()
        for sequence, callback in [
            (QKeySequence.Open, self._browse_files),
            ("F6", self._rename),
            ("Ctrl+Shift+Z", self._restore),
            ("F5", self._schedule_preview),
        ]:
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.triggered.connect(callback)
            self.addAction(action)

    def _update_rename_appearance(self, *_):
        loaded = bool(self.model.entries)
        if self.rename.property("filesLoaded") != loaded:
            self.rename.setProperty("filesLoaded", loaded)
            self.rename.style().unpolish(self.rename)
            self.rename.style().polish(self.rename)
            self.rename.update()
        if self.busy:
            reason = "Operation in progress"
        elif self.recovery_required:
            reason = "Recovery required before renaming"
        elif not loaded:
            reason = "Add files to rename"
        elif self.model.plan is None:
            reason = "Preview pending"
        elif self.model.plan.errors:
            reason = "Fix errors or exclude those files"
        elif not self.model.plan.changes:
            reason = "No filename changes"
        else:
            reason = f"Rename {len(self.model.plan.changes):,} files · F6"
        self.rename.setToolTip(reason)

    def _set_status(self, message):
        self.progress.set_message(message)

    def _update_layout_constraints(self):
        self.rule_controls.layout().invalidate()
        side_width = max(self.toolbar_left.sizeHint().width(), self.toolbar_right.sizeHint().width())
        self.toolbar_layout.setColumnMinimumWidth(0, side_width)
        self.toolbar_layout.setColumnMinimumWidth(2, side_width)
        hint = self.action_row.sizeHint()
        self.action_row.setMinimumSize(hint)
        self.action_row.setFixedHeight(hint.height())
        root = self.content_root
        margins = root.layout().contentsMargins()
        required = (
            max(hint.width(), self.rule_controls.sizeHint().width(), self.toolbar_layout.minimumSize().width())
            + margins.left()
            + margins.right()
        )
        root.setMinimumWidth(required)
        # Stop resizing before controls collide, including on narrow screens.
        self.setMinimumWidth(required)
        self.setMinimumHeight(self.centralWidget().minimumSizeHint().height())
        if not self.isMaximized() and not self.isMinimized() and self.width() < self.minimumWidth():
            self.resize(self.minimumWidth(), self.height())
        self.action_row.arrange()
        self.rule_list.fit_columns()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "layout_timer") and event.type() in {
            QEvent.FontChange,
            QEvent.ApplicationFontChange,
            QEvent.StyleChange,
            QEvent.WindowStateChange,
        }:
            self.layout_timer.start(0)
            self.row_resize_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_screen_connected", False) and self.windowHandle():
            self.windowHandle().screenChanged.connect(lambda *_: self.layout_timer.start(0))
            self._screen_connected = True
        self._update_layout_constraints()

    def _startup_notice(self):
        if self.startup_errors:
            self._message("Saved data", "\n".join(self.startup_errors))
        if self.recovery_required:
            self._set_status("An interrupted rename needs recovery. Use Recover Filenames to restore originals.")

    def _message(self, title, message):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setTextFormat(Qt.PlainText)
        box.setText(str(message)[:600])
        if len(str(message)) > 600:
            box.setDetailedText(str(message))
        box.exec()

    def _browse_files(self):
        if self.busy:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files", self.settings.value("folder", "", type=str))
        if paths:
            self.settings.setValue("folder", str(Path(paths[0]).parent))
            self.add_paths(paths)

    def _browse_folder(self):
        if self.busy:
            return
        path = QFileDialog.getExistingDirectory(self, "Add folder", self.settings.value("folder", "", type=str))
        if path:
            self.settings.setValue("folder", path)
            self.add_paths([path])

    def add_paths(self, paths: list[str]):
        if self.busy:
            return
        self._stop_preview()
        self.cancel_event.clear()
        recursive = self.settings.value("recursive", False, type=bool)
        self._set_status("Collecting files…")
        self._run_task(lambda _: scan_paths(paths, recursive, self.cancel_event.is_set), self._scanned)

    def _scanned(self, result):
        entries, errors = result
        sensitivity = {}
        seen = {path_key(entry.path, sensitivity) for entry in self.model.entries}
        combined = list(self.model.entries)
        for entry in entries:
            key = path_key(entry.path, sensitivity)
            if key not in seen:
                combined.append(entry)
                seen.add(key)
        self.model.reset_entries(combined)
        self._schedule_preview()
        hidden_count = sum(error.startswith("Skipped hidden item:") for error in errors)
        other_errors = [error for error in errors if not error.startswith("Skipped hidden item:")]
        self.collection_note = f" · {hidden_count} hidden items excluded" if hidden_count else ""
        if hidden_count:
            self._set_status(f"{len(combined)} files loaded{self.collection_note}")
        if other_errors:
            self._message("Some items were skipped", "\n".join(other_errors))

    def _clear(self):
        if not self.busy:
            self.model.reset_entries([])
            self._schedule_preview()

    def _sort(self, column, *, new_name=False):
        if self.busy or column == 2:
            return
        sort_key = (column, new_name)
        reverse = not self.sort_direction.get(sort_key, True)
        self.sort_direction[sort_key] = reverse
        destinations = {row.entry.path: row.destination for row in self.model.plan.files} if self.model.plan else {}
        key = {
            0: lambda entry: not entry.included,
            1: lambda entry: Path(destinations.get(entry.path, entry.path) if new_name else entry.path).name.casefold(),
        }[column]
        self.model.reset_entries(sorted(self.model.entries, key=key, reverse=reverse))
        self._schedule_preview()

    def _table_menu(self, position):
        if self.busy:
            return
        menu = QMenu(self)
        include = menu.addAction("Include selected")
        menu.addAction("Exclude selected")
        remove = menu.addAction("Remove selected from list")
        menu.addSeparator()
        all_files = menu.addAction("Include all")
        no_files = menu.addAction("Exclude all")
        choice = menu.exec(self.table.viewport().mapToGlobal(position))
        if choice is None:
            return
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        entries = []
        for index, entry in enumerate(self.model.entries):
            if choice == remove and index in selected:
                continue
            if choice in {all_files, no_files} or index in selected:
                entry = replace(entry, included=choice in {include, all_files})
            entries.append(entry)
        self.model.reset_entries(entries)
        self._schedule_preview()

    def _toggle_rules_panel(self):
        if not self.rules_collapsed:
            if self.isVisible():
                self.rules_height = self.splitter.sizes()[0]
        self.rules_collapsed = not self.rules_collapsed
        self.rule_body.setVisible(not self.rules_collapsed)
        self.collapse_rules.setChecked(not self.rules_collapsed)
        self.collapse_rules.setAccessibleDescription("Rules collapsed" if self.rules_collapsed else "Rules expanded")
        self.rules_panel.setVisible(not self.rules_collapsed)
        self.splitter.handle(1).setVisible(not self.rules_collapsed)
        height = 0 if self.rules_collapsed else self.rules_height
        self.splitter.setSizes([height, max(100, self.splitter.height() - self.splitter.handleWidth() - height)])

    def _fit_column(self, column):
        # Qt samples rows by default. Explicit fitting should consider every filename.
        if column in {1, 2}:
            self._resize_file_rows()
            return
        header = self.table.horizontalHeader()
        precision = header.resizeContentsPrecision()
        header.setResizeContentsPrecision(-1)
        self.table.resizeColumnToContents(column)
        header.setResizeContentsPrecision(precision)

    def _make_column_menu(self):
        menu = QMenu(self)
        for column, label in enumerate(self.model.HEADERS):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(column))
            action.setEnabled(column != 1)
            action.toggled.connect(lambda checked, index=column: self.table.setColumnHidden(index, not checked))
        menu.addSeparator()
        menu.addAction("Sort by original name", lambda: self._sort(1))
        menu.addAction("Sort by new name", lambda: self._sort(1, new_name=True))
        menu.addAction("Reset columns", self._reset_columns)
        return menu

    def _column_menu(self, position):
        menu = self._make_column_menu()
        menu.exec(self.table.horizontalHeader().mapToGlobal(position))
        menu.deleteLater()

    def _resize_file_rows(self):
        header = self.table.horizontalHeader()
        width = header.fontMetrics().horizontalAdvance("Status") + 20
        for row in range(self.model.rowCount()):
            status = self.model.index(row, 2).data(Qt.DisplayRole) or ""
            for word in status.split():
                document = QTextDocument()
                document.setDefaultFont(self.table.font())
                document.setDocumentMargin(0)
                document.setPlainText(word)
                width = max(width, math.ceil(document.idealWidth()) + 20)
        self.table.setColumnWidth(2, width)
        self.table.resizeRowsToContents()

    def _reset_columns(self):
        for table, widths in ((self.table, FILE_COLUMN_WIDTHS), (self.rule_list, RULE_COLUMN_WIDTHS)):
            for column, width in enumerate(widths):
                table.setColumnHidden(column, False)
                table.setColumnWidth(column, width)
        self._resize_file_rows()
        self.rule_list.fit_columns()

    def _restore_columns(self):
        for table, key in ((self.table, "file_columns_v3"), (self.rule_list, "rule_columns_v2")):
            try:
                saved = self.settings.value(key, "", type=str)
                if table is self.table and not saved:
                    saved = self.settings.value("file_columns_v2", "{}", type=str)
                state = json.loads(saved or "{}")
                widths, hidden = state.get("widths", []), state.get("hidden", [])
                if table is self.table and len(widths) == 4:
                    widths = widths[:3]
                    hidden = [column for column in hidden if column < 3]
                if len(widths) != table.model().columnCount() or not all(
                    type(width) is int and 24 <= width <= 32768 for width in widths
                ):
                    continue
                for column, width in enumerate(widths):
                    if table is not self.table or column != 2:
                        table.setColumnWidth(column, width)
                    if table is self.table and column != 1:
                        table.setColumnHidden(column, column in hidden)
            except (ValueError, TypeError, AttributeError):
                continue

    def _save_columns(self):
        for table, key in ((self.table, "file_columns_v3"), (self.rule_list, "rule_columns_v2")):
            hidden = [index for index in range(table.model().columnCount()) if table.isColumnHidden(index)]
            # Hidden sections report zero width; briefly reveal them to retain their saved size.
            for index in hidden:
                table.setColumnHidden(index, False)
            widths = [table.columnWidth(index) for index in range(table.model().columnCount())]
            for index in hidden:
                table.setColumnHidden(index, True)
            self.settings.setValue(key, json.dumps({"widths": widths, "hidden": hidden}))

    def _fill_rules(self, selected=-1):
        self.rule_list.blockSignals(True)
        self.rule_list.setRowCount(len(self.rules))
        targets = {"stem": "Name", "extension": "Extension", "name": "Full filename"}
        for row, rule in enumerate(self.rules):
            target = "name" if rule.kind == "repair" else "extension" if rule.kind == "extension" else rule.target
            for column, text in enumerate(("", RULE_LABELS[rule.kind], f"{targets[target]}: {rule_details(rule)}")):
                item = QTableWidgetItem(visible_text(text))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if column == 0:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if rule.enabled else Qt.Unchecked)
                item.setToolTip(visible_text(rule_summary(rule)))
                self.rule_list.setItem(row, column, item)
        self.rule_list.setCurrentCell(selected, 0)
        self.rule_list.blockSignals(False)
        self.rule_list.fit_columns()

    def _rules_changed(self, selected=-1):
        self._fill_rules(selected)
        self._fill_presets(self.selected_preset)
        self.settings.setValue("rules", json.dumps(preset_data("Current", self.rules)))
        self._schedule_preview()

    def _add_rule(self):
        if self.busy or len(self.rules) >= 100:
            return
        dialog = RuleDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.rules.append(dialog.result_rule)
            self._rules_changed(len(self.rules) - 1)

    def _edit_rule(self):
        index = self.rule_list.currentRow()
        if self.busy or index < 0:
            return
        dialog = RuleDialog(self, self.rules[index])
        if dialog.exec() == QDialog.Accepted:
            self.rules[index] = dialog.result_rule
            self._rules_changed(index)

    def _duplicate_rule(self):
        index = self.rule_list.currentRow()
        if index >= 0 and len(self.rules) < 100 and not self.busy:
            self.rules.insert(index + 1, replace(self.rules[index], options=dict(self.rules[index].options)))
            self._rules_changed(index + 1)

    def _remove_rule(self):
        index = self.rule_list.currentRow()
        if index >= 0 and not self.busy:
            del self.rules[index]
            self._rules_changed(min(index, len(self.rules) - 1))

    def _move_rule(self, direction):
        index = self.rule_list.currentRow()
        destination = index + direction
        if not self.busy and index >= 0 and 0 <= destination < len(self.rules):
            self.rules[index], self.rules[destination] = self.rules[destination], self.rules[index]
            self._rules_changed(destination)

    def _toggle_rule(self, item):
        if not self.busy and item.column() == 0:
            index = self.rule_list.row(item)
            self.rules[index] = replace(self.rules[index], enabled=item.checkState() == Qt.Checked)
            self._rules_changed(index)

    def _fill_presets(self, selected=""):
        self.selected_preset = selected if self.presets and selected in self.presets.presets else ""
        self.settings.setValue("selected_preset", self.selected_preset)
        name = self.selected_preset
        modified = bool(name and self.rules != self.presets.presets[name])
        text = f"{name} (modified)" if modified else name or "No preset selected"
        self.preset_label.setText(text)
        self.preset_label.setToolTip(text)
        self.preset_label.setAccessibleDescription(text)
        self.preset_more.setAccessibleDescription(
            f"Selected preset: {self.selected_preset}" if self.selected_preset else "No saved preset selected"
        )

    def _load_preset(self, name):
        if self.busy or not self.presets or name not in self.presets.presets:
            return
        self.rules = list(self.presets.presets[name])
        self._rules_changed()
        self._fill_presets(name)

    def _save_preset(self):
        if not self.presets:
            self._message("Presets unavailable", "Fix the unreadable preset library before saving presets.")
            return
        dialog = SavePresetDialog(self.selected_preset, self)
        if dialog.exec() == QDialog.Accepted:
            name = dialog.name.text()
            try:
                self.presets.save(name, self.rules)
                self._fill_presets(name.strip())
            except Exception as exc:
                self._message("Could not save preset", str(exc))

    def _make_preset_menu(self):
        menu = QMenu(self)
        load = QMenu("Load", menu)
        menu.addMenu(load)
        menu.load_menu = load  # Retain the Python wrapper for submenu actions.
        load.setEnabled(bool(self.presets and self.presets.presets))
        if self.presets:
            for name in sorted(self.presets.presets, key=lambda name: (name != self.selected_preset, name.casefold())):
                action = load.addAction(name.replace("&", "&&"))
                action.setData(name)
                action.setCheckable(True)
                action.setChecked(name == self.selected_preset)
                action.triggered.connect(lambda checked=False, preset=name: self._load_preset(preset))
        menu.addSeparator()
        save = menu.addAction("Save", self._save_preset)
        save.setEnabled(self.presets is not None)
        restore = menu.addAction("Import", self._restore_preset)
        restore.setEnabled(self.presets is not None)
        menu.addAction("Export", self._backup_preset)
        delete = menu.addAction("Delete", self._delete_preset)
        delete.setEnabled(bool(self.presets and self.presets.presets))
        return menu

    def _preset_menu(self):
        menu = self._make_preset_menu()
        menu.exec(self.preset_more.mapToGlobal(self.preset_more.rect().bottomLeft()))
        menu.deleteLater()

    def _delete_preset(self):
        if not self.presets or not self.presets.presets or self.busy:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Delete preset")
        layout = QVBoxLayout(dialog)
        choices = QListWidget()
        choices.setAccessibleName("Saved presets")
        names = sorted(self.presets.presets, key=str.casefold)
        choices.addItems(names)
        layout.addWidget(choices)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        delete = buttons.addButton("Delete", QDialogButtonBox.AcceptRole)
        delete.setEnabled(False)
        choices.currentRowChanged.connect(lambda row: delete.setEnabled(row >= 0))
        if self.selected_preset in names:
            choices.setCurrentRow(names.index(self.selected_preset))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(360, 300)
        if dialog.exec() != QDialog.Accepted or choices.currentItem() is None:
            dialog.deleteLater()
            return
        name = choices.currentItem().text()
        dialog.deleteLater()
        try:
            self.presets.delete(name)
            self._fill_presets(self.selected_preset)
        except Exception as exc:
            self._message("Preset error", str(exc))

    def _backup_preset(self):
        documents = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        if not documents.is_dir():
            documents = Path(QStandardPaths.writableLocation(QStandardPaths.HomeLocation))
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Preset",
            str(documents / "rename-preset.toml"),
            "Editable preset (*.toml);;JSON preset (*.json)",
        )
        if not path:
            return
        try:
            destination = Path(path)
            if not destination.suffix:
                destination = destination.with_suffix(".json" if "*.json" in selected_filter else ".toml")
            backup_preset(destination, self.selected_preset or "My rules", self.rules)
        except Exception as exc:
            self._message("Could not export preset", str(exc))

    def _restore_preset(self):
        if self.presets is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import Preset", "", "Rule presets (*.toml *.json)")
        if not path:
            return
        try:
            name, rules = restore_preset(Path(path))
            base, suffix = name, 2
            while name in self.presets.presets:
                name = f"{base[:110]} ({suffix})"
                suffix += 1
            self.presets.save(name, rules)
            self.rules = rules
            self._rules_changed()
            self._fill_presets(name)
        except Exception as exc:
            self._message("Could not import preset", str(exc))

    def _schedule_preview(self):
        if self.busy:
            return
        self.revision += 1
        self.model.results = {}
        self.model.show_plan(None)
        self.rename.setEnabled(False)
        self._update_rename_appearance()
        self.progress.preview(text="Updating preview…" if self.model.entries else "Ready")
        if self.process:
            self.process.kill()
        if not self.model.entries:
            self.debounce.stop()
            self._set_status("")
            return
        self._set_status("Updating preview…")
        self.debounce.start()

    def _launch_preview(self):
        if self.busy or not self.model.entries:
            return
        if self.process:
            self.debounce.start()
            return
        self.preview_temp = tempfile.TemporaryDirectory(prefix="file-renamer-preview-")
        directory = Path(self.preview_temp.name)
        request, response = directory / "request.json", directory / "response.json"
        try:
            atomic_json(
                request,
                {
                    "revision": self.revision,
                    "entries": [asdict(entry) for entry in self.model.entries],
                    "rules": [asdict(rule) for rule in self.rules],
                    "snapshot": {
                        "now": datetime.now().isoformat(),
                        "clipboard": QApplication.clipboard().text()
                        if any(":Clipboard:" in str(rule.options) or rule.kind == "pascal" for rule in self.rules)
                        else "",
                        "application_path": sys.executable,
                        "application_params": sys.argv[1:],
                    },
                },
            )
        except Exception as exc:
            self.preview_temp.cleanup()
            self.preview_temp = None
            self._set_status(f"Could not start preview: {exc}")
            return
        self.preview_revision = self.revision
        self.preview_reason = ""
        self.preview_ready = False
        process = QProcess(self)
        self.process = process
        process.finished.connect(self._preview_finished)
        process.errorOccurred.connect(self._preview_error)
        arguments = ["--preview-worker", str(request), str(response)]
        if not getattr(sys, "frozen", False):
            arguments = ["-m", "file_renamer", *arguments]
        process.start(sys.executable, arguments)
        self.deadline.start(15000)
        self.ready_poll.start()

    def _check_preview_ready(self):
        if self.preview_temp and not self.preview_ready:
            if (Path(self.preview_temp.name) / "response.json.ready").exists():
                self.preview_ready = True
                self.deadline.start(120000 if any(rule.behavior == "renamer" for rule in self.rules) else 5000)
                self.ready_poll.stop()

    def _preview_timeout(self):
        self.preview_reason = (
            "Preview exceeded its time limit. Simplify the rules or use fewer files."
            if self.preview_ready
            else "Preview worker could not start within 15 seconds."
        )
        if self.process:
            self.process.kill()

    def _preview_error(self, error):
        if error == QProcess.FailedToStart:
            self.preview_reason = "Could not start the preview worker. Check the application installation."
            self._preview_finished()

    def _preview_finished(self, *_):
        if not self.process:
            return
        self.deadline.stop()
        self.ready_poll.stop()
        process, directory = self.process, self.preview_temp
        self.process = None
        self.preview_temp = None
        try:
            if self.preview_revision == self.revision and not self.busy:
                if self.preview_reason:
                    raise ValueError(self.preview_reason)
                data = read_json(Path(directory.name) / "response.json")
                if "error" in data:
                    raise ValueError(data["error"])
                plan = RenamePlan.from_dict(data["plan"])
                if plan.revision == self.revision:
                    self.model.show_plan(plan)
                    changes, errors = len(plan.changes), len(plan.errors)
                    self.progress.preview(changes, f"{changes:,} files to rename" if changes else "No files to rename")
                    unchanged = sum(row.entry.included and not row.error and not row.changed for row in plan.files)
                    self.rename.setToolTip(f"Rename {changes:,} files · F6")
                    self.rename.setEnabled(changes > 0 and errors == 0 and not self.recovery_required)
                    self._update_rename_appearance()
                    self._set_status(
                        "Recovery required — restore original filenames before renaming."
                        if self.recovery_required
                        else f"{changes:,} ready to rename  ·  {unchanged:,} unchanged  ·  {errors:,} errors"
                        + getattr(self, "collection_note", "")
                        + ("  — Fix errors or uncheck those files." if errors else "")
                    )
        except Exception as exc:
            self.progress.preview(text="Preview unavailable")
            self._set_status(f"Preview unavailable: {exc}")
            self.rename.setEnabled(False)
            self._update_rename_appearance()
        finally:
            if directory:
                directory.cleanup()
            process.deleteLater()

    def _stop_preview(self):
        self.debounce.stop()
        self.revision += 1
        self.rename.setEnabled(False)
        self._update_rename_appearance()
        if self.process:
            self.process.kill()

    def _set_busy(self, busy):
        self.busy = busy
        self.model.locked = busy
        for widget in [
            self.add_files,
            self.add_folder,
            self.clear,
            self.settings_button,
            self.rule_list,
            self.preset_more,
            *self.rule_buttons,
        ]:
            widget.setEnabled(not busy)
        self.rename.setEnabled(False)
        self._update_rename_appearance()
        self.undo.setEnabled(False if busy else self.undo.isEnabled())
        if not busy:
            self._update_undo()

    def _run_task(self, function, callback, operation="Collecting"):
        self.operation = operation
        self.progress_total = 0
        self._set_busy(True)
        if operation == "Renaming" and self.model.plan:
            self.progress.preview(len(self.model.plan.changes))
        else:
            self.progress.file_count = 0
            self.progress.setRange(0, 0)
        self.progress.setFormat(f"{operation} files…")
        task = TaskThread(function, self)
        self.task = task
        task.progress.connect(self._progress)
        # Results arrive before QThread.finished; defer callbacks until the thread has stopped.
        outcome = {}
        task.result.connect(lambda value: outcome.update(result=value))
        task.failed.connect(lambda message: outcome.update(error=message))

        def finished():
            self.task = None
            self._set_busy(False)
            task.deleteLater()
            if "error" in outcome:
                self._finish_progress(False)
                self._set_status(f"Operation failed — {outcome['error']}")
                self._message("Operation could not finish", outcome["error"])
                self._update_undo()
            elif "result" in outcome:
                result = outcome["result"]
                self._finish_progress(getattr(result, "success", True))
                callback(outcome["result"])

        task.finished.connect(finished)
        task.start()

    def _progress(self, done, total):
        self.progress_total = total // 2
        files = total // 2
        self.progress.file_count = files
        self.progress.setRange(0, max(files, 1))
        self.progress.setValue(max(0, done - files))
        if done <= files:
            self.progress.setFormat(f"Preparing {done:,} / {files:,} files · %p%")
        else:
            self.progress.setFormat(f"{self.operation} {done - files:,} / {files:,} files · %p%")

    def _finish_progress(self, success):
        maximum = self.progress.file_count or 100
        self.progress.setRange(0, maximum)
        self.progress.setValue(maximum if success else 0)
        if not success:
            self.progress.setFormat("Operation failed")
        elif self.operation == "Collecting":
            self.progress.setFormat("Files collected · 100%")
        else:
            label = "Renamed" if self.operation == "Renaming" else "Restored"
            self.progress.setFormat(f"{label} {self.progress_total:,} / {self.progress_total:,} files · 100%")

    def _rename(self):
        if self.busy or not self.rename.isEnabled() or not self.model.plan:
            return
        plan = self.model.plan
        self._stop_preview()
        self.cancel_event.clear()
        self._set_status("Renaming files…")
        self._run_task(
            lambda progress: self.manager.execute(plan, self.cancel_event.is_set, progress), self._renamed, "Renaming"
        )

    def _renamed(self, result):
        mapping = dict(result.paths)
        entries = []
        outcomes = {}
        for entry in self.model.entries:
            path = mapping.get(entry.path, entry.path)
            entries.append(replace(entry, path=path))
            label = "Restored" if self.operation == "Restoring" else "Renamed"
            outcomes[path] = label if result.success and path != entry.path else "Unchanged"
            if not result.success:
                outcomes[path] = "Recovery required" if result.recovery_required else "Not renamed"
        self.model.reset_entries(entries)
        self.model.results = outcomes
        self.model.refresh()
        self.recovery_required = result.recovery_required
        self._update_undo()
        if result.success:
            self.progress.setToolTip(result.message)
        else:
            self._set_status(f"Operation failed — {result.message}")
        # Do not silently apply numbering/insertion rules for a second time after a rename.
        self.rename.setEnabled(False)
        self._update_rename_appearance()
        if not result.success:
            self._message("Rename result", result.message)

    def _restore(self):
        if self.busy or not self.undo.isEnabled():
            return
        self._stop_preview()
        self._set_status("Restoring original filenames…")
        self._run_task(lambda progress: self.manager.restore(progress), self._renamed, "Restoring")

    def _update_undo(self):
        try:
            journal = self.manager.load()
            self.recovery_required = bool(journal and journal["status"] in {"active", "needs_recovery"})
            self.undo.setText("RECOVER" if self.recovery_required else "UNDO")
            self.undo.setToolTip(
                "Recover original filenames" if self.recovery_required else "Undo last rename · Ctrl+Shift+Z"
            )
            self._update_layout_constraints()
            self.undo.setEnabled(
                not self.busy and bool(journal and journal["status"] in {"active", "needs_recovery", "committed"})
            )
        except Exception as exc:
            self.recovery_required = True
            self.undo.setEnabled(False)
            self._set_status(f"Recovery journal could not be read: {exc}")

    def _settings(self):
        if self.busy:
            return
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            self.settings.setValue("theme", dialog.theme.currentText())
            self.settings.setValue("recursive", dialog.recursive.isChecked())
            apply_theme(QApplication.instance(), dialog.theme.currentText())

    def _open_donate(self):
        if not QDesktopServices.openUrl(QUrl(KOFI_URL)):
            self._message("Support on Ko-fi", f"Open this address in your browser:\n{KOFI_URL}")

    def _help(self):
        box = QMessageBox(self)
        box.setWindowTitle("File Renamer · Help")
        box.setTextFormat(Qt.PlainText)
        box.setText(
            "1. Add files or drop a folder onto the window.\n"
            "2. Add rules. They run from top to bottom; click its On button to disable it.\n"
            "3. Compare each original filename with the proposed name directly beneath it.\n"
            "4. Click Rename. Only included files change, exactly as previewed.\n\n"
            "Click column headings to sort; numbering follows the displayed order. Right-click files "
            "to include, exclude or remove them. F5 refreshes the preview, F6 renames, "
            "Ctrl+Shift+Z restores the latest batch.\n\n"
            "Extensions are protected by default. New rules use one-based positions and native regex: "
            "$1 inserts the first capture group. Legacy presets keep zero-based positions and Python regex "
            r"(\g<1> for the first capture group). "
            "Folders collect files; their names are never changed. No file contents are modified.\n\n"
            "Existing files are never overwritten. Undo survives restart and refuses conflicts or changed "
            "files. Starting another batch replaces the previous undo history.\n\n"
            "Resize or maximize the window, or drag the gripper beneath Rules. "
            "The Rules button shows or hides the list without moving the action buttons.\n"
            "Names wrap automatically; long status messages wrap too. Right-click a file column heading "
            "to show/hide columns or reset widths. "
            "Window position, size, and column settings are remembered.\n"
            "Choose a rule from the list on the left; edit its definitions on the right.\n"
            "Preset offers Load, Save, Import, Export, and Delete "
            "(editable TOML or JSON). "
            "Horizontal resizing stops before action buttons overlap.\n"
            "Progress includes preparation and completed filenames. Wait for an operation to finish "
            "before closing the app.\n"
            "Invalid names are blocked. Add Repair filename to fix characters explicitly.\n\n"
            "After a batch, edit a rule or press F5 to preview another rename.\n\n"
            f"Version {__version__} · Steady State Studio · MIT license\n"
            "Design inspired by Square Photo Padder."
        )
        box.setInformativeText(f'<a href="{KOFI_URL}">Support on Ko-fi</a>')
        box.setTextFormat(Qt.AutoText)
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.exec()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if not self.busy and event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        if not self.busy:
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                event.acceptProposedAction()
                self.add_paths(paths)

    def closeEvent(self, event):
        if self.busy:
            self._set_status("Wait for the operation to finish before closing.")
            event.ignore()
            return
        self.debounce.stop()
        self.revision += 1
        if self.process:
            self.process.kill()
            self.process.waitForFinished(3000)
        self.settings.setValue("selected_preset", self.selected_preset)
        self.settings.setValue("rules", json.dumps(preset_data("Current", self.rules)))
        self.settings.setValue("window_geometry", self.saveGeometry())
        self._save_columns()
        self.settings.setValue("rules_collapsed", self.rules_collapsed)
        self.settings.setValue("rules_height", self.rules_height if self.rules_collapsed else self.splitter.sizes()[0])
        self.settings.sync()
        event.accept()
