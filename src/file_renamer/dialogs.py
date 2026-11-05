from __future__ import annotations

import json
import math

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .appearance_controls import AppearanceSettingsDialog
from .choice_buttons import AccentCheckBox, AccentRadioButton
from .desktop_geometry import available_geometry as desktop_available_geometry
from .desktop_geometry import workarea_provider
from .models import RuleSpec
from .registry import LABELS as COMPAT_LABELS
from .registry import MULTILINE, REGISTRY, SIGNED, effective_options
from .rule_controls import (
    MappingEditor,
    PascalHighlighter,
    TextEditor,
    insert_metadata,
    open_script_repository,
    script_examples,
    transfer_text,
)
from .rules import CHOICES, RULE_DEFAULTS, RULE_LABELS, RULE_ORDER, validate_rule
from .translit_presets import alphabets
from .window_screen import observe_window_screen

LABELS = {
    "match": "Match text",
    "occurrence": "Occurrence",
    "from_right": "Count from right",
    "delimiter": "Delimiter",
    "end_delimiter": "End delimiter",
    "include_delimiters": "Include delimiters",
    "digits": "Digits",
    "whitespace": "Whitespace",
    "punctuation": "Punctuation",
    "symbols": "Symbols",
    "characters": "Custom characters",
    "template": "New arrangement",
    "platform": "Compatibility",
    "text": "Text",
    "find": "Find",
    "replacement": "Replace with",
    "position": "Position",
    "index": "Position (0 = beginning)",
    "start": "Start",
    "count": "Characters to delete",
    "case_sensitive": "Case sensitive",
    "all": "Replace all occurrences",
    "mode": "Case",
    "step": "Step",
    "width": "Minimum digits",
    "separator": "Separator",
    "per_folder": "Restart in each folder",
    "trim": "Trim edges",
    "collapse": "Combine spaces, underscores and hyphens",
    "pattern": "Pattern",
}


# Presentation only: option identifiers and saved values remain unchanged.
RULE_SECTIONS = {
    "insert": (("Insert", ("text",)), ("Where", ("position", "index", "match", "occurrence", "case_sensitive"))),
    "delete": (
        ("Delete", ("mode",)),
        ("From / Until", ("start", "count", "from_right", "delimiter", "end_delimiter", "include_delimiters")),
    ),
    "remove": (("Remove", ("text",)), ("Occurrences", ("occurrence", "all", "case_sensitive"))),
    "replace": (("Find / Replace", ("find", "replacement")), ("Occurrences", ("occurrence", "all", "case_sensitive"))),
    "rearrange": (("Split", ("delimiter",)), ("New arrangement", ("template",))),
    "extension": (("New file extension", ("text",)),),
    "strip": (("Characters to strip", ("digits", "whitespace", "punctuation", "symbols", "characters")),),
    "case": (("Case change", ("mode",)),),
    "number": (
        ("Numbering", ("start", "step", "width")),
        ("Insert where", ("position", "separator")),
        ("Reset", ("per_folder",)),
    ),
    "padding": (("Zero padding", ("width",)),),
    "cleanup": (("Clean Up", ("trim", "collapse", "separator")),),
    "accents": (),
    "regex": (("Regular Expressions", ("pattern", "replacement")), ("Options", ("case_sensitive", "all"))),
    "repair": (("Filename compatibility", ("platform",)),),
}
CHOICE_LABELS = {
    "replace": "Replace current name",
    "prefix": "Prefix",
    "suffix": "Suffix",
    "index": "Position",
    "before": "Before text",
    "after": "After text",
    "first": "First",
    "last": "Last",
    "all": "All",
    "legacy": "Use saved first/all setting",
    "position": "Position / count",
    "between": "Between delimiters",
    "lower": "all lower case",
    "upper": "ALL UPPER CASE",
    "title": "Capitalize Every Word",
    "sentence": "First letter capital",
    "swap": "iNVERT cASE",
}


class ToggleButton(AccentCheckBox):
    """Compatibility name for the native checkbox with button presentation."""


class ChoiceGroup(QWidget):
    """Visible exclusive choices, retaining saved option values."""

    currentIndexChanged = Signal(int)
    currentTextChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.group = QButtonGroup(self)
        self.values = []
        self.rows = []
        self.row_widgets = []
        self.vertical = False
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.group.idToggled.connect(self._changed)

    def addItem(self, label, value):
        row = QGridLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        button = AccentRadioButton(label)
        self.group.addButton(button, len(self.values))
        self.values.append(value)
        row.addWidget(button, 0, 0)
        row.setColumnStretch(1, 1)
        self.rows.append(row)
        self.row_widgets.append([button])
        index = len(self.values) - 1
        self.layout().addLayout(row, index if self.vertical else index // 2, 0 if self.vertical else index % 2)

    def findData(self, value):
        return self.values.index(value) if value in self.values else -1

    def setCurrentIndex(self, index):
        button = self.group.button(index)
        if button:
            button.setChecked(True)

    def currentData(self):
        index = self.group.checkedId()
        return self.values[index] if index >= 0 else None

    def _changed(self, index, checked):
        if checked:
            self.currentIndexChanged.emit(index)
            self.currentTextChanged.emit(self.group.button(index).text())

    def addAccessory(self, value, widget):
        index = self.findData(value)
        self.row_widgets[index].append(widget)
        self.reflow(max(1, self.width()))

    def reflow(self, width):
        for widgets in self.row_widgets:
            for widget in widgets:
                widget.ensurePolished()
        columns = 1 if self.vertical else 2
        needed = sum(max((widgets[0].sizeHint().width() for widgets in self.row_widgets[offset::2]),
                         default=0) for offset in (0, 1)) + 12
        if needed > width:
            columns = 1
        grid = self.layout()
        for _ in self.rows:
            grid.takeAt(0)
        cell_width = max(1, (width - (columns - 1) * grid.spacing()) // columns)
        for index, (row, widgets) in enumerate(zip(self.rows, self.row_widgets)):
            while row.count():
                row.takeAt(0)
            for column in range(row.columnCount()):
                row.setColumnStretch(column, 0)
            line, column, used = 0, 0, 0
            for widget in widgets:
                needed = widget.sizeHint().width()
                if column and used + needed + row.spacing() > cell_width:
                    line, column, used = line + 1, 0, 0
                row.addWidget(widget, line, column)
                column += 1
                used += needed + row.spacing()
            row.setColumnStretch(column, 1)
            row.invalidate()
            grid.addLayout(row, index // columns, index % columns)
        grid.invalidate()
        self.updateGeometry()



def _dialog_workarea_limits(dialog):
    area = desktop_available_geometry(dialog, dialog.screen().availableGeometry())
    frame = dialog.frameGeometry()
    return (area, max(1, area.width() - max(40, frame.width() - dialog.width())),
            max(1, area.height() - max(80, frame.height() - dialog.height())))


class FittedFormDialog(QDialog):
    """Fit ordinary forms to their content; keep long lists scrollable."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.fit_timer = QTimer(self)
        self.fit_timer.setSingleShot(True)
        self.fit_timer.timeout.connect(self.fit_to_screen)
        self._workarea_provider = workarea_provider(QApplication.instance())
        self._workarea_provider.changed.connect(self._workarea_changed)

    def fit_to_screen(self):
        self.ensurePolished()
        outer = self.layout()
        if not hasattr(self, "_fitted_body"):
            self._fitted_body = QWidget()
            body_layout = QVBoxLayout(self._fitted_body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(outer.spacing())
            # Keep the final action group outside the constrained form body.
            while outer.count() > 1:
                item = outer.takeAt(0)
                body_layout.addWidget(item.widget())
            self.content_scroll = QScrollArea()
            self.content_scroll.setFrameShape(QScrollArea.NoFrame)
            self.content_scroll.setWidgetResizable(True)
            self.content_scroll.setWidget(self._fitted_body)
            outer.insertWidget(0, self.content_scroll)
        body_layout = self._fitted_body.layout()
        self._fitted_body.setMinimumHeight(0)
        body_layout.activate()
        outer.activate()
        _, cap_width, cap_height = _dialog_workarea_limits(self)
        margins = outer.contentsMargins()
        extra_width = margins.left() + margins.right()
        actions = outer.itemAt(outer.count() - 1)
        if isinstance(actions.widget(), QDialogButtonBox):
            actions.widget().setOrientation(Qt.Horizontal)
            if actions.minimumSize().width() > max(1, cap_width - extra_width):
                actions.widget().setOrientation(Qt.Vertical)
        width = min(cap_width,
                    max(self._fitted_body.sizeHint().width(), actions.sizeHint().width()) + extra_width)
        body_height = body_layout.totalHeightForWidth(max(1, width - extra_width))
        body_height = max(self._fitted_body.minimumSizeHint().height(),
                          body_height if body_height > 0 else body_layout.sizeHint().height())
        self._fitted_body.setMinimumHeight(body_height)
        height = body_height + actions.sizeHint().height() + outer.spacing() + margins.top() + margins.bottom()
        self.setFixedSize(width, min(cap_height, height))

    def showEvent(self, event):
        super().showEvent(event)
        self._screen_changed()
        self.fit_to_screen()
        observe_window_screen(self, self._screen_changed)

    def _screen_changed(self, *_):
        screen = self.screen()
        previous = getattr(self, "_fit_screen", None)
        if previous is not screen:
            if previous is not None:
                try:
                    previous.availableGeometryChanged.disconnect(self._screen_changed)
                except RuntimeError:
                    pass
            screen.availableGeometryChanged.connect(self._screen_changed)
            self._fit_screen = screen
        self._workarea_provider.refresh()
        self._workarea_changed()

    def _workarea_changed(self, *_):
        if self.isVisible():
            self.fit_timer.start(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        frame = self.frameGeometry()
        metrics = (frame.width() - self.width(), frame.height() - self.height())
        if metrics != getattr(self, "_fit_frame_metrics", None):
            self._fit_frame_metrics = metrics
            if hasattr(self, "fit_timer"):
                self.fit_timer.start(0)

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() in {QEvent.FontChange, QEvent.ApplicationFontChange, QEvent.StyleChange,
                             QEvent.DevicePixelRatioChange}
                and self.layout() and hasattr(self, "fit_timer")):
            self._screen_changed()


class PresetList(QListWidget):
    def sizeHint(self):
        metrics = self.fontMetrics()
        longest = max((metrics.horizontalAdvance(self.item(row).text()) for row in range(self.count())), default=0)
        width = min(max(240, longest + 40), metrics.horizontalAdvance("M" * 36) + 40)
        height = min(8, max(1, self.count())) * (metrics.height() + 8) + 2 * self.frameWidth()
        return QSize(width, height)


class LoadPresetDialog(FittedFormDialog):
    def __init__(self, names, current="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Load preset")
        layout = QVBoxLayout(self)
        self.choices = PresetList()
        self.choices.setAccessibleName("Saved presets")
        self.choices.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.choices.setTextElideMode(Qt.ElideRight)
        for name in sorted(names, key=lambda value: (value != current, value.casefold())):
            item = QListWidgetItem(name, self.choices)
            item.setToolTip(name)
        if self.choices.count():
            self.choices.setCurrentRow(0)
        layout.addWidget(self.choices)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.load_button = buttons.addButton("Load", QDialogButtonBox.AcceptRole)
        self.load_button.setObjectName("primary")
        self.load_button.setDefault(True)
        self.load_button.setEnabled(self.choices.currentItem() is not None)
        self.choices.currentRowChanged.connect(lambda row: self.load_button.setEnabled(row >= 0))
        self.choices.itemDoubleClicked.connect(lambda *_: self.accept())
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_name(self):
        item = self.choices.currentItem()
        return item.text() if item else ""


class SavePresetDialog(FittedFormDialog):
    def __init__(self, name="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save preset")
        if parent:
            self.setFont(parent.font())
        layout = QVBoxLayout(self)
        label = QLabel("Name (an existing name replaces that preset)")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.name = QLineEdit(name)
        self.name.setAccessibleName("Preset name")
        layout.addWidget(self.name)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name.selectAll()
        self.name.setFocus()


class RuleTypeList(QListWidget):
    def keyPressEvent(self, event):
        # Keep Home/End navigation consistent across platforms.
        if event.key() in {Qt.Key_Home, Qt.Key_End}:
            indices = range(self.count()) if event.key() == Qt.Key_Home else reversed(range(self.count()))
            for index in indices:
                if self.item(index).flags() & Qt.ItemIsSelectable:
                    self.setCurrentRow(index)
                    self.scrollToItem(self.item(index))
                    return
        super().keyPressEvent(event)


TEXT_EDITOR_KINDS = frozenset({
    "insert", "remove", "replace", "rearrange", "regex", "translit", "pascal", "userinput", "mapping",
})
EDITOR_WIDTHS_KEY = "ui/rule_editor_widths_v1"


class RuleDialog(QDialog):
    def __init__(self, parent=None, rule: RuleSpec | None = None):
        super().__init__(parent)
        from .application_paths import application_settings

        self.settings = getattr(parent, "settings", None)
        if self.settings is None:
            self.settings = application_settings()
        self._editor_widths = {}
        try:
            saved = str(self.settings.value(EDITOR_WIDTHS_KEY, "{}"))
            values = json.loads(saved) if len(saved) <= 4096 else {}
            if isinstance(values, dict):
                self._editor_widths = {key: round(value) for key, value in values.items()
                                       if key in TEXT_EDITOR_KINDS and isinstance(value, (float, int))
                                       and not isinstance(value, bool) and math.isfinite(value)
                                       and 80 <= value <= 20000}
        except (TypeError, ValueError):
            pass
        self._fitting_rule_dialog = False
        self._environment_fit_pending = True
        self._fit_area_signature = None
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setSizeGripEnabled(False)
        self.setWindowTitle("Edit rule" if rule else "Add a rule")
        self.setObjectName("ruleDialog")
        self.result_rule = rule
        self.widgets = {}
        self.inline_widgets = set()
        self.check_groups = []
        layout = QVBoxLayout(self)
        panes = QHBoxLayout()
        self.kind = RuleTypeList()
        self.kind.setAccessibleName("Rule type")
        self.kind.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for key in RULE_ORDER:
            item = QListWidgetItem(RULE_LABELS[key], self.kind)
            item.setData(Qt.UserRole, key)
            item.setSizeHint(QSize(0, self.kind.fontMetrics().height() + 6))
        self.kind.setCurrentRow(0)
        panes.addWidget(self.kind)
        definitions = QGroupBox()
        definitions.setFlat(True)
        definitions.setObjectName("ruleDefinitions")
        self.definitions = definitions
        definition_layout = QVBoxLayout(definitions)
        definition_layout.setContentsMargins(8, 8, 8, 8)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        self.hint.setTextFormat(Qt.PlainText)
        definition_layout.addWidget(self.hint)
        self.target = ChoiceGroup()
        self.target.vertical = True
        for label, value in [
            ("Name without extension", "stem"),
            ("Extension only", "extension"),
            ("Complete filename", "name"),
        ]:
            self.target.addItem(label, value)
        self.target.setCurrentIndex(self.target.findData("stem"))
        self.target_label = QLabel("Apply to")
        definition_layout.addWidget(self.target_label)
        definition_layout.addWidget(self.target)
        self.fields = QWidget()
        self.form = QFormLayout(self.fields)
        self.form.setContentsMargins(0, 4, 0, 4)
        self.form.setVerticalSpacing(4)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        definition_layout.addWidget(self.fields)
        definition_layout.addStretch()
        scroll = QScrollArea()
        self.editor_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(definitions)
        panes.addWidget(scroll, 2)
        layout.addLayout(panes, 1)
        buttons = QWidget()
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        primary = QPushButton("Save Rule" if rule else "Add Rule")
        primary.setObjectName("primary")
        primary.setDefault(True)
        close = QPushButton("Cancel" if rule else "Close")
        primary.clicked.connect(self._accept)
        close.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(primary)
        button_layout.addWidget(close)
        self.buttons = buttons
        layout.addWidget(buttons)
        self.kind.currentRowChanged.connect(self._fields)
        if rule:
            for index in range(self.kind.count()):
                if self.kind.item(index).data(Qt.UserRole) == ("translit" if rule.kind == "accents" else rule.kind):
                    if rule.kind == "accents":
                        self.kind.item(index).setData(Qt.UserRole, "accents")
                    self.kind.setCurrentRow(index)
                    break
            self.target.setCurrentIndex(self.target.findData(rule.target))
        self._fields()
        if rule:
            restored = effective_options(rule) if rule.behavior == "renamer" else rule.options
            for key, value in restored.items():
                widget = self.widgets[key]
                if isinstance(widget, QCheckBox):
                    widget.setChecked(value)
                elif isinstance(widget, QSpinBox):
                    widget.setValue(value)
                elif isinstance(widget, ChoiceGroup):
                    widget.setCurrentIndex(widget.findData(value))
                else:
                    widget.setText(value)
        self._visibility()
        self.fit_timer = QTimer(self)
        self.fit_timer.setSingleShot(True)
        self.fit_timer.timeout.connect(self._fit_dialog)
        self._workarea_provider = workarea_provider(QApplication.instance())
        self._workarea_provider.changed.connect(self._workarea_changed)
        self._fit_dialog()

    def _fit_dialog(self):
        if self._fitting_rule_dialog:
            return
        self._fitting_rule_dialog = True
        try:
            self.ensurePolished()
            for widget in self.findChildren(QWidget):
                widget.ensurePolished()
            available, max_width, max_height = _dialog_workarea_limits(self)
            button_layout = self.buttons.layout()
            button_layout.setDirection(QBoxLayout.LeftToRight)
            if button_layout.minimumSize().width() > max_width:
                button_layout.setDirection(QBoxLayout.TopToBottom)
            self._fit_area_signature = available.getRect()
            margins = self.layout().contentsMargins()
            gap = self.layout().spacing()
            overhead = margins.top() + margins.bottom() + gap + self.buttons.sizeHint().height()
            label_width = row_height = 0
            for row in range(self.kind.count()):
                item = self.kind.item(row)
                metrics = QFontMetrics(item.font().resolve(self.kind.font()))
                row_height = max(row_height, metrics.height() + 6)
                item.setSizeHint(QSize(0, metrics.height() + 6))
                label_width = max(label_width, metrics.horizontalAdvance(item.text()))
            scroll_width = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
            list_width = label_width + 24 + 2 * self.kind.frameWidth() + scroll_width
            self.kind.setFixedWidth(min(list_width, max_width // 2))
            self.kind.setMinimumHeight(0)
            self.definitions.setMinimumHeight(0)
            non_editor = self.kind.width() + margins.left() + margins.right() + gap
            field_limit = max(1, max_width - non_editor)
            preferred = self._editor_widths.get(self._kind()) if self._kind() in TEXT_EDITOR_KINDS else None
            self._reflow_choices(field_limit - 24 - scroll_width)
            self.form.invalidate()
            self.definitions.layout().invalidate()
            minimum_field = self.definitions.minimumSizeHint().width()
            natural_field = max(minimum_field, self.definitions.sizeHint().width())
            editor_width = min(field_limit, max(minimum_field, preferred if preferred is not None else natural_field))
            self._reflow_choices(max(1, editor_width - 24 - scroll_width))
            self.form.invalidate()
            self.fields.updateGeometry()
            definition_layout = self.definitions.layout()
            definition_layout.invalidate()
            editor_height = max(self.definitions.minimumSizeHint().height(),
                                definition_layout.totalHeightForWidth(max(1, editor_width - scroll_width)))
            # A category catalogue is scrollable content, not a reason to make
            # a short form as tall as every category combined.
            catalog_height = min(6, self.kind.count()) * row_height + 2 * self.kind.frameWidth()
            height = min(max_height, max(catalog_height, editor_height + 4) + overhead)
            width = min(max_width, non_editor + editor_width)
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            if self._kind() in TEXT_EDITOR_KINDS:
                self.setMinimumWidth(min(max_width, non_editor + minimum_field))
                self.setMaximumWidth(max_width)
                self.setFixedHeight(height)
                self.resize(width, height)
            else:
                self.setFixedSize(width, height)
            self.definitions.setMinimumHeight(editor_height)
            QTimer.singleShot(0, self, self._fit_editor_height)
        finally:
            self._fitting_rule_dialog = False
            self._environment_fit_pending = False

    def _fit_editor_height(self):
        # Qt resolves a form's wrapping and style margins after assigning its
        # final width. Keep that width and measure the resulting content height.
        width = self.editor_scroll.viewport().width()
        self.definitions.setMinimumHeight(0)
        self._reflow_choices(max(1, width - 24))
        self.form.invalidate()
        self.fields.updateGeometry()
        self.definitions.layout().invalidate()
        needed = max(self.definitions.minimumSizeHint().height(), self.definitions.heightForWidth(width))
        self.definitions.setMinimumHeight(needed)
        margins = self.layout().contentsMargins()
        overhead = margins.top() + margins.bottom() + self.layout().spacing() + self.buttons.sizeHint().height()
        row_height = max(self.kind.item(row).sizeHint().height() for row in range(self.kind.count()))
        catalogue = min(6, self.kind.count()) * row_height + 2 * self.kind.frameWidth()
        _, _, maximum = _dialog_workarea_limits(self)
        self._fitting_rule_dialog = True
        try:
            self.setFixedHeight(min(maximum, max(catalogue, needed + 4) + overhead))
        finally:
            self._fitting_rule_dialog = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        frame = self.frameGeometry()
        metrics = (frame.width() - self.width(), frame.height() - self.height())
        if metrics != getattr(self, "_fit_frame_metrics", None):
            self._fit_frame_metrics = metrics
            if hasattr(self, "fit_timer"):
                self._environment_fit_pending = True
                self.fit_timer.start(0)
        if (not hasattr(self, "fit_timer") or self._fitting_rule_dialog or self._environment_fit_pending
                or not self.isVisible() or self._kind() not in TEXT_EDITOR_KINDS
                or event.size().width() == event.oldSize().width()):
            return
        if desktop_available_geometry(self, self.screen().availableGeometry()).getRect() != self._fit_area_signature:
            return
        # Only window-system user resizing updates the preference. Automatic
        # fitting, style changes and monitor clamping must never replace it.
        if event.spontaneous():
            margins = self.layout().contentsMargins()
            width = (event.size().width() - self.kind.width() - margins.left() - margins.right()
                     - self.layout().spacing())
            self._editor_widths[self._kind()] = max(80, width)
            self.settings.setValue(EDITOR_WIDTHS_KEY, json.dumps(self._editor_widths, sort_keys=True))
            self.settings.sync()
            self._schedule_fit()

    def _reflow_choices(self, width):
        for widget in (self.target, *self.widgets.values()):
            if isinstance(widget, ChoiceGroup):
                widget.reflow(width)
        for container, left, right in self.check_groups:
            layout = container.layout()
            layout.removeWidget(right)
            columns = left.sizeHint().width() + right.sizeHint().width() + layout.spacing()
            layout.addWidget(right, 1 if columns > width else 0, 0 if columns > width else 1)

    def _schedule_fit(self):
        if hasattr(self, "fit_timer"):
            self.fit_timer.start(0)

    def _set_option_visible(self, key, visible):
        widget = self.widgets[key]
        if key in self.inline_widgets:
            if self._kind() == "insert" and key == "match":
                visible = self.widgets["position"].currentData() == "after"
            widget.setEnabled(visible)
        elif self.form.getWidgetPosition(widget)[0] >= 0:
            self.form.setRowVisible(widget, visible)
        else:
            widget.setVisible(visible)

    def _compact_checks(self):
        row = 0
        while row < self.form.rowCount() - 1:
            first = self.form.itemAt(row, QFormLayout.FieldRole)
            second = self.form.itemAt(row + 1, QFormLayout.FieldRole)
            if (first and second and isinstance(first.widget(), QCheckBox)
                    and isinstance(second.widget(), QCheckBox)):
                left, right = first.widget(), second.widget()
                self.form.takeRow(row + 1)
                self.form.takeRow(row)
                container = QWidget()
                layout = QGridLayout(container)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.addWidget(left, 0, 0)
                layout.addWidget(right, 0, 1)
                self.check_groups.append((container, left, right))
                self.form.insertRow(row, container)
            row += 1

    def _inline_fields(self):
        kind = self._kind()
        bindings = {
            "insert": (("position", "index", "index"), ("position", "index", "from_right"),
                       ("position", "after", "match")),
            "delete": (("from_mode", "position", "start"), ("from_mode", "delimiter", "delimiter"),
                       ("until_mode", "count", "count"), ("until_mode", "delimiter", "end_delimiter")),
            "number": (("position", "index", "index"),),
            "randomize": (("position", "index", "index"),),
        }
        for group_key, value, key in bindings.get(kind, ()):
            widget = self.widgets[key]
            row = self.form.takeRow(widget)
            if row.labelItem:
                label = row.labelItem.widget()
                label.hide()
                label.deleteLater()
            self.widgets[group_key].addAccessory(value, widget)
            self.inline_widgets.add(key)
        if kind == "insert":
            # Two inline fields edit the same persisted match option.
            match = self.widgets["match"]
            before = QLineEdit(match.text())
            before.setMaxLength(match.maxLength())
            before.setAccessibleName("Before text")
            match.textChanged.connect(before.setText)
            before.textChanged.connect(match.setText)
            group = self.widgets["position"]
            group.addAccessory("before", before)
            group.currentIndexChanged.connect(lambda *_: before.setEnabled(group.currentData() == "before"))
            before.setEnabled(group.currentData() == "before")

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "fit_timer") and event.type() in {
            QEvent.FontChange,
            QEvent.ApplicationFontChange,
            QEvent.StyleChange,
            QEvent.DevicePixelRatioChange,
        }:
            self._screen_changed()

    def showEvent(self, event):
        super().showEvent(event)
        self._screen_changed()
        observe_window_screen(self, self._screen_changed)
        self._fit_dialog()

    def _screen_changed(self, *_):
        screen = self.screen()
        previous = getattr(self, "_fit_screen", None)
        if previous is not screen:
            if previous is not None:
                try:
                    previous.availableGeometryChanged.disconnect(self._screen_changed)
                except RuntimeError:
                    pass
            screen.availableGeometryChanged.connect(self._screen_changed)
            self._fit_screen = screen
        self._workarea_provider.refresh()
        self._environment_fit_pending = True
        self.fit_timer.start(0)

    def _workarea_changed(self):
        if self.isVisible():
            self._environment_fit_pending = True
            self.fit_timer.start(0)

    def _kind(self):
        return self.kind.currentItem().data(Qt.UserRole)

    def _fields(self, *_):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.widgets.clear()
        self.inline_widgets.clear()
        self.check_groups.clear()
        kind = self._kind()
        self.target.setVisible(self._behavior() == "legacy")
        self.target_label.setVisible(self._behavior() == "legacy")
        if self._behavior() == "renamer":
            self._compat_fields()
            return
        self.definitions.setTitle(RULE_LABELS[kind] + (" (Legacy)" if kind != "repair" else ""))
        self.target.setEnabled(kind not in {"extension", "repair"})
        if kind == "repair":
            self.target.setCurrentIndex(self.target.findData("name"))
        section_starts = {keys[0]: title for title, keys in RULE_SECTIONS[kind] if len(RULE_SECTIONS[kind]) > 1}
        keys = [key for _, keys in RULE_SECTIONS[kind] for key in keys]
        for key in keys:
            default = RULE_DEFAULTS[kind][key]
            if key in section_starts:
                heading = QLabel(section_starts[key])
                heading.setObjectName("sectionHeading")
                heading.setWordWrap(True)
                self.form.addRow(heading)
            label_text = "Mode" if key == "mode" else LABELS[key]
            label_text = {
                ("insert", "text"): "Insert",
                ("remove", "text"): "Remove",
                ("replace", "replacement"): "Replace",
                ("extension", "text"): "New file extension (without the dot)",
                ("number", "start"): "Index starts",
                ("number", "width"): "Pad with zeros to length",
                ("delete", "from_right"): "Right-to-left",
            }.get((kind, key), label_text)
            if type(default) is bool:
                widget = AccentCheckBox(label_text)
                widget.setChecked(default)
            elif type(default) is int:
                widget = QSpinBox()
                widget.setRange(-1_000_000 if key == "step" else 0, 255 if key == "width" else 1_000_000)
                widget.setValue(default)
            elif key in CHOICES.get(kind, {}):
                widget = ChoiceGroup()
                widget.vertical = key in {"position", "from_mode", "until_mode"}
                values = CHOICES[kind][key]
                if kind == "number" and key == "position":
                    values = ("prefix", "suffix")
                for value in values:
                    widget.addItem(CHOICE_LABELS.get(value, value), value)
                widget.setCurrentIndex(widget.findData(default))
            else:
                widget = QLineEdit(default)
                widget.setMaxLength(8192)
            self.widgets[key] = widget
            widget.setAccessibleName(label_text)
            if isinstance(widget, (QCheckBox, ChoiceGroup)):
                self.form.addRow(widget)
            else:
                label = QLabel(label_text)
                label.setWordWrap(True)
                label.setBuddy(widget)
                self.form.addRow(label, widget)
            if isinstance(widget, ChoiceGroup):
                widget.currentTextChanged.connect(self._visibility)
        self._visibility()
        hints = {
            "insert": "Insert text at the beginning, end, a position, or beside matching text.",
            "remove": "Remove matching text from the selected part of each filename.",
            "replace": "Replace matching text with new text.",
            "case": "Change capitalization in the selected part of each filename.",
            "cleanup": "Trim edges and combine repeated spaces, underscores, and hyphens.",
            "strip": "Remove selected character sets or each custom character. Example: item12 \u2192 item.",
            "accents": "Remove Latin accents: caf\u00e9 \u2192 cafe. Other scripts are preserved.",
            "rearrange": "Split on the delimiter, then use numbered parts: blue_jacket + {2}_{1} \u2192 jacket_blue. "
            "Use {{ and }} for literal braces. Missing parts are preview errors.",
            "repair": "Repairs the complete filename. This computer follows your OS; Windows-compatible "
            "also repairs Windows reserved names. Length and collision errors still need attention.",
            "regex": "Python regular expressions. Example: ^(.*)_(\\d+)$ → \\g<2>_\\g<1>\n"
            "Use \\g<0> for the whole match. Evaluations stop after five seconds.",
            "number": "Numbers follow the displayed file order. Sorting or excluding files updates the sequence.",
            "extension": "Enter the extension without a dot. Leave empty to remove it. File contents do not change.",
            "delete": "Positions start at zero. Characters beyond the end are ignored.",
            "padding": "Sets the minimum width of each number, removing excess leading zeros first.",
        }
        self.hint.setText(hints[kind])
        self.hint.setVisible(bool(hints[kind]))
        self._schedule_fit()

    def _visibility(self, *_):
        kind = self._kind()
        if self._behavior() == "renamer":
            self._compat_visibility()
            return

        def choice(key):
            return self.widgets[key].currentData()

        for key, widget in self.widgets.items():
            visible = True
            if kind == "insert":
                position = choice("position")
                if key == "index":
                    visible = position == "index"
                if key in {"match", "occurrence", "case_sensitive"}:
                    visible = position in {"before", "after"}
            if kind == "delete":
                mode = choice("mode")
                if key in {"start", "count", "from_right"}:
                    visible = mode == "position"
                if key in {"delimiter", "include_delimiters"}:
                    visible = mode != "position"
                if key == "end_delimiter":
                    visible = mode == "between"
            if kind in {"remove", "replace"} and key == "all":
                visible = choice("occurrence") == "legacy"
            self._set_option_visible(key, visible)
        self._schedule_fit()

    def _accept(self):
        options = {}
        for key, widget in self.widgets.items():
            if isinstance(widget, QCheckBox):
                options[key] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                options[key] = widget.value()
            elif isinstance(widget, ChoiceGroup):
                options[key] = widget.currentData()
            else:
                options[key] = widget.text()
        target = "name" if self._kind() == "repair" else self.target.currentData()
        rule = RuleSpec(
            self._kind(), target, self.result_rule.enabled if self.result_rule else True, options, self._behavior()
        )
        try:
            validate_rule(rule)
        except ValueError as exc:
            QMessageBox.warning(self, "Check rule", str(exc))
            return
        self.result_rule = rule
        self.accept()

    def _behavior(self):
        if self._kind() == "repair":
            return "legacy"
        if self.result_rule and self.result_rule.behavior == "legacy" and self._kind() in RULE_DEFAULTS:
            return "legacy"
        return "renamer"

    def _compat_fields(self):
        kind = self._kind()
        definition = REGISTRY[kind]
        self.definitions.setTitle(definition.label)
        self.hint.setText(definition.hint)
        self.hint.setVisible(bool(definition.hint))
        sections = definition.sections + (
            (("General", ("skip_extension",)),) if "skip_extension" in definition.defaults else ()
        )
        for title, keys in sections:
            if title != "General":
                heading = QLabel(title)
                heading.setObjectName("sectionHeading")
                self.form.addRow(heading)
            for key in keys:
                default = definition.defaults[key]
                label_text = COMPAT_LABELS[key]
                if type(default) is bool:
                    widget = AccentCheckBox(label_text)
                    widget.setChecked(default)
                elif type(default) is int:
                    widget = QSpinBox()
                    widget.setRange(-1000000 if key in SIGNED else 0, 1000000)
                    widget.setValue(default)
                elif key in definition.choices:
                    widget = ChoiceGroup()
                    widget.vertical = key in {"position", "from_mode", "until_mode"}
                    values = definition.choices[key]
                    if kind == "insert" and key == "position":
                        values = ("prefix", "suffix", "index", "after", "before", "replace")
                    for value in values:
                        widget.addItem(CHOICE_LABELS.get(value, value.replace("_", " ").capitalize()), value)
                    widget.setCurrentIndex(widget.findData(default))
                elif key == "mapping":
                    widget = MappingEditor()
                elif key in MULTILINE:
                    widget = TextEditor(default)
                    widget.setMinimumHeight(170)
                    if key == "script":
                        widget.setProperty("pascal", True)
                        widget.highlighter = PascalHighlighter(widget.document())
                else:
                    widget = QLineEdit(default)
                    widget.setMaxLength(8192)
                self.widgets[key] = widget
                widget.setAccessibleName(label_text)
                if isinstance(widget, (QCheckBox, ChoiceGroup)):
                    self.form.addRow(widget)
                    if isinstance(widget, QCheckBox):
                        widget.toggled.connect(self._visibility)
                else:
                    label = QLabel(label_text)
                    label.setWordWrap(True)
                    label.setBuddy(widget)
                    self.form.addRow(label, widget)
                if isinstance(widget, ChoiceGroup):
                    widget.currentIndexChanged.connect(self._visibility)
                if key in {"text", "replacement", "template"} and kind in {"insert", "replace", "rearrange"}:
                    button = QPushButton("Insert meta tag")
                    button.clicked.connect(lambda checked=False, editor=widget: insert_metadata(self, editor))
                    button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
                    self.form.addRow(button)
                    QShortcut("Ctrl+Ins", widget, activated=lambda editor=widget: insert_metadata(self, editor))
                if kind == "date" and key in {"find_formats", "format"}:
                    button = QPushButton("Date formats")
                    menu = QMenu(button)
                    for pattern in (
                        "yyyy-mm-dd",
                        "yyyymmdd",
                        "dd-mm-yyyy",
                        "mm-dd-yyyy",
                        "yyyy-mm-dd hh-nn-ss",
                        "dd mmm yyyy",
                    ):
                        menu.addAction(pattern, lambda checked=False, editor=widget, text=pattern: editor.setText(text))
                    button.setMenu(menu)
                    button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
                    self.form.addRow(button)
                if key in MULTILINE:
                    menu_button = QPushButton(
                        "Alphabet"
                        if key == "alphabet"
                        else "Table"
                        if key == "mapping"
                        else "Scripts"
                        if key == "script"
                        else "Options"
                    )
                    menu = QMenu(menu_button)
                    for action in (
                        "Load from file",
                        "Load from clipboard",
                        "Save to file",
                        "Save to clipboard",
                        "Clear",
                    ):
                        menu.addAction(
                            action,
                            lambda checked=False, editor=widget, action=action, table=key == "mapping": transfer_text(
                                self, editor, action, table
                            ),
                        )
                    if key == "alphabet":
                        for name, alphabet in alphabets().items():
                            menu.addAction(
                                name, lambda checked=False, editor=widget, text=alphabet: editor.setText(text)
                            )
                    if key == "script":
                        for name, source in script_examples().items():
                            menu.addAction(name, lambda checked=False, editor=widget, text=source: editor.setText(text))
                        menu.addAction(
                            "Open script repository",
                            lambda checked=False, editor=widget: open_script_repository(self, editor),
                        )
                        compile_button = QPushButton("Try to Compile")
                        compile_button.clicked.connect(self._compile_script)
                        compile_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
                        self.form.addRow(compile_button)
                        goto = QPushButton("Go to line")
                        goto.clicked.connect(self._goto_line)
                        goto.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
                        self.form.addRow(goto)
                        help_button = QPushButton("Functions / Help")
                        help_button.clicked.connect(self._script_help)
                        help_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
                        self.form.addRow(help_button)
                        QShortcut("Ctrl+T", widget, activated=self._compile_script)
                        QShortcut("Ctrl+G", widget, activated=self._goto_line)
                        QShortcut("Ctrl+L", widget, activated=menu_button.showMenu)
                        QShortcut("F1", widget, activated=self._script_help)
                    menu_button.setMenu(menu)
                    menu_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
                    self.form.addRow(menu_button)
        self._inline_fields()
        self._compact_checks()
        self._compat_visibility()

    def _compat_visibility(self):
        kind = self._kind()

        def choice(key):
            return self.widgets[key].currentData()

        def checked(key):
            return self.widgets[key].isChecked()

        visible = {}
        if kind == "insert":
            visible = {
                "index": choice("position") == "index",
                "from_right": choice("position") == "index",
                "match": choice("position") in {"before", "after"},
            }
        elif kind == "delete":
            visible = {
                "start": choice("from_mode") == "position",
                "delimiter": choice("from_mode") == "delimiter",
                "count": choice("until_mode") == "count",
                "end_delimiter": choice("until_mode") == "delimiter",
            }
        elif kind in {"number", "randomize"}:
            visible["index"] = choice("position") == "index"
            if kind == "number":
                visible.update(symbols=choice("system").startswith("custom"), width=checked("pad"))
        elif kind == "padding":
            visible.update(
                width=checked("pad_numbers"),
                length=checked("pad_text"),
                characters=checked("pad_text"),
                position=checked("pad_text"),
            )
        elif kind == "extension":
            visible.update(
                text=checked("change") and not checked("detect"), case_sensitive=checked("remove_duplicates")
            )
        elif kind == "date":
            for key in ("years", "months", "days", "hours", "minutes", "seconds", "milliseconds"):
                visible[key] = checked("adjust_time")
        for flag, text in (
            ("use_characters", "characters"),
            ("use_unicode_range", "unicode_range"),
            ("force_fragments", "fragments"),
            ("use_short_months", "short_months"),
            ("use_long_months", "long_months"),
        ):
            if flag in self.widgets:
                visible[text] = checked(flag)
        for key, show in visible.items():
            self._set_option_visible(key, show)
        self._schedule_fit()

    def _compile_script(self):
        from .pascal import PascalSession

        try:
            with PascalSession() as session:
                session.compile(self.widgets["script"].text())
            QMessageBox.information(self, "Pascal Script", "Compiled successfully")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Pascal Script", str(exc))

    def _script_help(self):
        from .pascal import FUNCTION_NAMES

        dialog = FittedFormDialog(self)
        dialog.setWindowTitle("Pascal Script functions")
        layout = QVBoxLayout(dialog)
        description = QLabel(
            "Ctrl+Space: complete function. Ctrl+T: compile. Ctrl+G: go to line.\n"
            "FileName is writable; FilePath is the original path.\n"
            "File writes, DLL imports and external programs are unavailable."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        functions = PresetList()
        functions.addItems(FUNCTION_NAMES)
        layout.addWidget(functions)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _goto_line(self):
        number, okay = QInputDialog.getInt(self, "Go to line", "Line", 1, 1, 1000000)
        if okay:
            editor = self.widgets["script"]
            cursor = editor.textCursor()
            block = editor.document().findBlockByNumber(number - 1)
            if not block.isValid():
                return
            cursor.setPosition(block.position())
            editor.setTextCursor(cursor)
            editor.setFocus()


class SettingsDialog(AppearanceSettingsDialog):
    def __init__(self, settings, parent=None):
        from PySide6.QtWidgets import QApplication

        from .themes import apply_theme

        super().__init__(settings, parent, theme_key="theme", apply_callback=lambda: apply_theme(
            QApplication.instance(), settings.value("theme", "system", type=str)))
        self.theme = self.controls.theme
        self.recursive = AccentCheckBox("Include subfolders when adding folders")
        self.recursive.setChecked(settings.value("recursive", False, type=bool))
        self.content_layout.addWidget(self.recursive)
        label = QLabel("Files stay on your computer. Symbolic links and junctions are skipped.")
        label.setWordWrap(True)
        self.content_layout.addWidget(label)

    def accept(self):
        self.settings.setValue("recursive", self.recursive.isChecked())
        super().accept()
