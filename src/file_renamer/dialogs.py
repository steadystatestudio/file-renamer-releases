from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QPainter, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
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
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

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


class ToggleButton(QPushButton):
    """A keyboard-accessible boolean button whose label wraps at narrow widths."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setAccessibleName(text)
        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def minimumSizeHint(self):
        return QSize(100, self.fontMetrics().height() + 20)

    def heightForWidth(self, width):
        return (
            self.fontMetrics()
            .boundingRect(QRect(0, 0, max(1, width - 28), 10000), Qt.TextWordWrap, self.text())
            .height()
            + 20
        )

    def sizeHint(self):
        width = min(360, super().sizeHint().width())
        return QSize(width, self.heightForWidth(width))

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        painter = QPainter(self)
        self.style().drawControl(QStyle.CE_PushButton, option, painter, self)
        color = self.palette().buttonText().color()
        if self.isChecked() and self.isEnabled():
            color = Qt.white
        painter.setPen(color)
        painter.drawText(self.rect().adjusted(12, 8, -12, -8), Qt.AlignCenter | Qt.TextWordWrap, self.text())


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
        button = QRadioButton(label)
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
            grid.addLayout(row, index // columns, index % columns)



class SavePresetDialog(QDialog):
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
        self.resize(440, self.sizeHint().height())
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


class RuleDialog(QDialog):
    def __init__(self, parent=None, rule: RuleSpec | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit rule" if rule else "Add a rule")
        self.setObjectName("ruleDialog")
        font = self.font()
        font.setPointSizeF(12)
        self.setFont(font)
        self.result_rule = rule
        self.widgets = {}
        self.inline_widgets = set()
        self.check_groups = []
        layout = QVBoxLayout(self)
        panes = QHBoxLayout()
        self.kind = RuleTypeList()
        font = self.kind.font()
        font.setPointSizeF(12)
        self.kind.setFont(font)
        self.kind.setAccessibleName("Rule type")
        self.kind.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for key in RULE_ORDER:
            item = QListWidgetItem(RULE_LABELS[key], self.kind)
            item.setData(Qt.UserRole, key)
            item.setSizeHint(QSize(0, self.kind.fontMetrics().height() + 6))
        self.kind.setCurrentRow(0)
        panes.addWidget(self.kind)
        definitions = QGroupBox()
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
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(definitions)
        panes.addWidget(scroll, 2)
        layout.addLayout(panes, 1)
        buttons = QWidget()
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        primary = QPushButton("Save Rule" if rule else "Add Rule")
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
        self._fit_dialog()

    def _fit_dialog(self):
        available = self.screen().availableGeometry()
        max_width, max_height = max(320, available.width() - 40), max(240, available.height() - 80)
        margins = self.layout().contentsMargins()
        overhead = margins.top() + margins.bottom() + self.layout().spacing() + self.buttons.sizeHint().height()
        list_height = 2 * self.kind.frameWidth()
        label_width = 0
        for row in range(self.kind.count()):
            item = self.kind.item(row)
            metrics = QFontMetrics(item.font().resolve(self.kind.font()))
            height = metrics.height() + 6
            item.setSizeHint(QSize(0, height))
            list_height += height
            label_width = max(label_width, metrics.horizontalAdvance(item.text()))
        list_width = label_width + 24 + 2 * self.kind.frameWidth()
        if list_height + overhead > max_height:
            list_width += self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        self.kind.setFixedWidth(list_width)
        self.definitions.setMinimumHeight(0)
        # Reflow to the actual screen width before measuring minimum sizes.
        field_limit = max_width - list_width - margins.left() - margins.right() - self.layout().spacing()
        scroll_width = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        self._reflow_choices(field_limit - 24 - scroll_width)
        self.form.invalidate()
        self.definitions.layout().invalidate()
        field_width = max(420, self.definitions.minimumSizeHint().width())
        gap = self.layout().spacing()
        width = min(max_width, list_width + field_width + margins.left() + margins.right() + gap)
        editor_width = width - list_width - margins.left() - margins.right() - gap
        self._reflow_choices(editor_width - 24 - scroll_width)
        definition_layout = self.definitions.layout()
        definition_layout.invalidate()
        editor_height = max(definition_layout.minimumSize().height(),
                            definition_layout.totalHeightForWidth(editor_width))
        height = min(max_height, max(list_height, editor_height + 4) + overhead)
        self.setMinimumSize(min(width, max_width), min(360, height))
        self.resize(width, height)
        self.definitions.setMinimumHeight(editor_height)

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
        }:
            self.fit_timer.start(0)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_screen_connected", False) and self.windowHandle():
            self.windowHandle().screenChanged.connect(lambda *_: self.fit_timer.start(0))
            self._screen_connected = True
        self._fit_dialog()

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
                widget = QCheckBox(label_text)
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
                    widget = QCheckBox(label_text)
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

        dialog = QDialog(self)
        dialog.setWindowTitle("Pascal Script functions")
        layout = QVBoxLayout(dialog)
        description = QLabel(
            "Ctrl+Space: complete function. Ctrl+T: compile. Ctrl+G: go to line.\n"
            "FileName is writable; FilePath is the original path.\n"
            "File writes, DLL imports and external programs are unavailable."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        functions = QListWidget()
        functions.addItems(FUNCTION_NAMES)
        layout.addWidget(functions)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(560, 600)
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


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QVBoxLayout(self)
        self.theme = QComboBox()
        self.theme.addItems(["system", "dark", "light"])
        self.theme.setCurrentText(settings.value("theme", "system", type=str))
        layout.addWidget(QLabel("Appearance"))
        layout.addWidget(self.theme)
        self.recursive = ToggleButton("Include subfolders when adding folders")
        self.recursive.setChecked(settings.value("recursive", False, type=bool))
        layout.addWidget(self.recursive)
        label = QLabel("Files stay on your computer. Symbolic links and junctions are skipped.")
        label.setWordWrap(True)
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
