"""ReNamer-style option registry. Legacy options live in rules.py."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Definition:
    label: str
    sections: tuple
    defaults: dict
    choices: dict
    hint: str


REGISTRY = {}


def register(kind, label, sections, defaults, choices=None, hint=""):
    REGISTRY[kind] = Definition(label, tuple(sections), defaults, choices or {}, hint)


PLACE = ("prefix", "suffix", "index", "replace")
SKIP = {"skip_extension": True}
OCC = ("all", "first", "last")
register(
    "insert",
    "Insert",
    [("Insert", ("text",)), ("Where", ("position", "index", "from_right", "match"))],
    dict(text="", position="prefix", index=1, from_right=False, match="", **SKIP),
    {"position": (*PLACE, "before", "after")},
    "Insert text or metadata. Positions start at 1.",
)
register(
    "delete",
    "Delete",
    [
        ("From", ("from_mode", "start", "delimiter")),
        ("Until", ("until_mode", "count", "end_delimiter")),
        ("Options", ("delete_current", "from_right", "keep_delimiters")),
    ],
    dict(
        from_mode="position",
        start=1,
        delimiter="",
        until_mode="count",
        count=1,
        end_delimiter="",
        delete_current=False,
        from_right=False,
        keep_delimiters=False,
        **SKIP,
    ),
    {"from_mode": ("position", "delimiter"), "until_mode": ("count", "delimiter", "end")},
    "Delete a range, counting from either end. Positions start at 1.",
)
for kind, label in [("remove", "Remove"), ("replace", "Replace")]:
    text = {"text": ""} if kind == "remove" else {"find": "", "replacement": ""}
    register(
        kind,
        label,
        [(label, tuple(text)), ("Options", ("occurrence", "case_sensitive", "whole_words", "wildcards"))],
        dict(**text, occurrence="all", case_sensitive=False, whole_words=False, wildcards=False, **SKIP),
        {"occurrence": OCC},
        "Separate multiple entries with *|*. Wildcards: ?, *, [a-z].",
    )
register(
    "rearrange",
    "Rearrange",
    [("Split using", ("split_mode", "delimiter", "from_right")), ("New pattern", ("template",))],
    dict(split_mode="delimiters", delimiter="", template="$0", from_right=False, **SKIP),
    {"split_mode": ("delimiters", "exact", "positions")},
    "Separate delimiters with | and one-based positions with *|*. Use $1, $-1, or $0 for the whole name.",
)
register(
    "extension",
    "Extension",
    [
        ("New extension", ("change", "text", "append", "detect")),
        ("Duplicates", ("remove_duplicates", "case_sensitive")),
    ],
    dict(change=True, text="", append=False, detect=False, remove_duplicates=False, case_sensitive=False),
    hint="Enter the extension without a dot. Signature detection reads file contents.",
)
register(
    "strip",
    "Strip",
    [
        ("Character sets", ("english", "digits", "symbols", "brackets", "characters", "unicode_range")),
        ("Options", ("position", "invert", "case_sensitive")),
    ],
    dict(
        english=False,
        digits=False,
        symbols=False,
        brackets=False,
        characters="",
        unicode_range="",
        position="everywhere",
        invert=False,
        case_sensitive=False,
        **SKIP,
    ),
    {"position": ("everywhere", "leading", "trailing")},
    "Unicode ranges use hexadecimal codes, e.g. 200B-200D,FEFF.",
)
register(
    "case",
    "Case",
    [("Case change", ("mode", "preserve")), ("Force case", ("fragments",)), ("Extension", ("extension_case",))],
    dict(mode="title", preserve=False, fragments="", extension_case="unchanged", **SKIP),
    {
        "mode": ("title", "lower", "upper", "swap", "first", "sentence", "none"),
        "extension_case": ("unchanged", "lower", "upper"),
    },
    "Separate forced-case fragments with commas, e.g. CD,DVD,iPad.",
)
register(
    "number",
    "Serialize",
    [
        ("Indexing", ("start", "repeat", "step", "reset_every", "reset_folder", "reset_name")),
        ("Numbering system", ("system", "symbols", "pad", "width")),
        ("Insert where", ("position", "index")),
    ],
    dict(
        start=1,
        repeat=1,
        step=1,
        reset_every=0,
        reset_folder=False,
        reset_name=False,
        system="decimal",
        symbols="",
        pad=False,
        width=1,
        position="prefix",
        index=1,
        **SKIP,
    ),
    {
        "system": ("decimal", "letters", "roman", "music", "chinese", "custom_alphabetic", "custom_numeric"),
        "position": PLACE,
    },
    "Numbering follows included files in displayed order; resets follow changes in that order.",
)
register(
    "randomize",
    "Randomize",
    [
        ("Characters", ("digits", "english", "characters")),
        ("Sequence", ("length", "unique")),
        ("Insert where", ("position", "index")),
    ],
    dict(digits=True, english=False, characters="", length=4, unique=False, position="prefix", index=1, **SKIP),
    {"position": PLACE},
    "Names are generated in preview. Rename uses those exact generated names.",
)
register(
    "padding",
    "Padding",
    [
        ("Number sequences", ("pad_numbers", "width", "remove_zeros")),
        ("Text padding", ("pad_text", "length", "characters", "position")),
    ],
    dict(
        pad_numbers=True,
        width=3,
        remove_zeros=False,
        pad_text=False,
        length=10,
        characters="0",
        position="left",
        **SKIP,
    ),
    {"position": ("left", "right")},
)
register(
    "cleanup",
    "Clean Up",
    [
        ("Strip bracket contents", ("round", "square", "curly")),
        ("Replace with spaces", ("replace_chars", "skip_versions")),
        ("Options", ("fix_spaces", "normalize_spaces", "strip_emoji", "strip_marks", "camel_case", "sharepoint")),
    ],
    dict(
        round=False,
        square=False,
        curly=False,
        replace_chars="",
        skip_versions=False,
        fix_spaces=True,
        normalize_spaces=False,
        strip_emoji=False,
        strip_marks=False,
        camel_case=False,
        sharepoint=False,
        **SKIP,
    ),
)
register(
    "translit",
    "Translit",
    [("Alphabet", ("alphabet",)), ("Direction", ("direction",)), ("Options", ("auto_case",))],
    dict(alphabet="", direction="forward", auto_case=True, **SKIP),
    {"direction": ("forward", "backward")},
    "Enter one pair per line, separated by =. Put longer matches first. Choose Alphabet to load or save a map.",
)
register(
    "date",
    "Reformat Date",
    [
        ("Formats", ("find_formats", "format", "whole_words")),
        ("Custom month names", ("short_months", "long_months")),
        ("Adjust time by", ("years", "months", "days", "hours", "minutes", "seconds", "milliseconds")),
    ],
    dict(
        find_formats="yyyy-mm-dd",
        format="yyyymmdd",
        whole_words=False,
        short_months="",
        long_months="",
        years=0,
        months=0,
        days=0,
        hours=0,
        minutes=0,
        seconds=0,
        milliseconds=0,
        **SKIP,
    ),
    hint="Separate input formats with |. Delphi date tokens: yyyy, mm, dd, hh, nn, ss, zzz.",
)
register(
    "regex",
    "Regular Expressions",
    [("Expression", ("pattern", "replacement")), ("Options", ("case_sensitive",))],
    dict(pattern="", replacement="", case_sensitive=False, **SKIP),
    hint="Use $1, $2 for captured groups and $0 for the whole match. Evaluations have a time limit.",
)
register(
    "pascal",
    "Pascal Script",
    [("Script", ("script",))],
    dict(script="begin\n  FileName := 'Example ' + FileName;\nend."),
    hint=(
        "Pascal naming scripts. FileName is writable; FilePath is the original path. "
        "File writes and external calls are excluded."
    ),
)
register(
    "userinput",
    "User Input",
    [("New names", ("names",)), ("Insert where", ("position",))],
    dict(names="", position="replace", **SKIP),
    {"position": ("prefix", "suffix", "replace")},
    "One line per included file in displayed order. Files beyond the list remain unchanged.",
)
register(
    "mapping",
    "Mapping",
    [("Mapping table", ("mapping",)), ("Options", ("reuse", "partial", "inverse", "case_sensitive"))],
    dict(mapping="", reuse=False, partial=False, inverse=False, case_sensitive=False, **SKIP),
    hint="Map old names to new names. Without reuse, each row can match only once per preview.",
)

# Separate switches preserve text while its corresponding option is disabled.
OPTION_SWITCHES = {
    "strip": {"use_characters": "characters", "use_unicode_range": "unicode_range"},
    "randomize": {"use_characters": "characters"},
    "case": {"force_fragments": "fragments"},
    "date": {"use_short_months": "short_months", "use_long_months": "long_months"},
}
for kind, switches in OPTION_SWITCHES.items():
    definition = REGISTRY[kind]
    sections = tuple(
        (
            title,
            tuple(
                item
                for key in keys
                for item in (
                    (next(flag for flag, text in switches.items() if text == key), key)
                    if key in switches.values()
                    else (key,)
                )
            ),
        )
        for title, keys in definition.sections
    )
    REGISTRY[kind] = Definition(
        definition.label,
        sections,
        definition.defaults | dict.fromkeys(switches, False),
        definition.choices,
        definition.hint,
    )

definition = REGISTRY["cleanup"]
REGISTRY["cleanup"] = Definition(
    definition.label,
    tuple(
        (
            title,
            ("space_underscore", "space_dash", "space_dot", "space_comma", *keys)
            if title == "Replace with spaces"
            else keys,
        )
        for title, keys in definition.sections
    ),
    definition.defaults | dict.fromkeys(("space_underscore", "space_dash", "space_dot", "space_comma"), False),
    definition.choices,
    definition.hint,
)

definition = REGISTRY["date"]
REGISTRY["date"] = Definition(
    definition.label,
    tuple(
        (title, ("adjust_time", *keys) if title == "Adjust time by" else keys) for title, keys in definition.sections
    ),
    definition.defaults | {"adjust_time": False},
    definition.choices,
    definition.hint,
)

LABELS = {
    "adjust_time": "Adjust time by",
    "space_underscore": "Underscore (_)",
    "space_dash": "Dash (-)",
    "space_dot": "Dot (.)",
    "space_comma": "Comma (,)",
    "use_characters": "Use user-defined characters",
    "use_unicode_range": "Use Unicode range",
    "force_fragments": "Force case for fragments",
    "use_short_months": "Custom short month names",
    "use_long_months": "Custom long month names",
    "skip_extension": "Skip extension",
    "from_mode": "From",
    "until_mode": "Until",
    "start": "Position / index starts",
    "index": "Position (1 = beginning)",
    "from_right": "Right-to-left",
    "delete_current": "Delete current name",
    "keep_delimiters": "Do not remove delimiters",
    "whole_words": "Whole words only",
    "wildcards": "Interpret wildcards",
    "split_mode": "Split using",
    "change": "New file extension",
    "append": "Append to original filename",
    "detect": "Detect using binary signature",
    "remove_duplicates": "Remove duplicate extensions",
    "english": "English letters",
    "brackets": "Brackets",
    "unicode_range": "Unicode range",
    "invert": "Strip all except selected",
    "preserve": "Preserve case",
    "fragments": "Force case for fragments",
    "extension_case": "Extension always",
    "repeat": "Repeat",
    "reset_every": "Reset every (0 = never)",
    "reset_folder": "Reset if folder changes",
    "reset_name": "Reset if file name changes",
    "system": "Numbering system",
    "symbols": "Symbols / custom alphabet",
    "pad": "Pad with zeros",
    "pad_numbers": "Add zero padding",
    "remove_zeros": "Remove zero padding",
    "pad_text": "Add text padding",
    "length": "Length",
    "unique": "Unique if possible",
    "round": "Round brackets (…)",
    "square": "Square brackets […]",
    "curly": "Curly brackets {…}",
    "replace_chars": "Replace these characters with spaces",
    "skip_versions": "Skip number sequences",
    "fix_spaces": "Fix spaces",
    "normalize_spaces": "Normalize Unicode spaces",
    "strip_emoji": "Strip Unicode emoji",
    "strip_marks": "Strip Unicode marks",
    "camel_case": "Insert spaces before capitals",
    "sharepoint": "Prepare for SharePoint",
    "alphabet": "Alphabet pairs",
    "direction": "Direction",
    "auto_case": "Auto case adjustment",
    "find_formats": "Find date/time formats",
    "format": "Convert to date/time format",
    "short_months": "Custom short months",
    "long_months": "Custom long months",
    "years": "Years",
    "months": "Months",
    "days": "Days",
    "hours": "Hours",
    "minutes": "Minutes",
    "seconds": "Seconds",
    "milliseconds": "Milliseconds",
    "script": "Pascal source",
    "names": "One name per line",
    "mapping": "Match / New name",
    "reuse": "Allow reuse",
    "partial": "Partial match",
    "inverse": "Inverse mapping",
    "text": "Text",
    "find": "Find",
    "replacement": "Replace",
    "template": "New pattern",
    "delimiter": "Delimiters / positions",
    "end_delimiter": "Until delimiter",
    "position": "Position",
    "occurrence": "Occurrences",
    "case_sensitive": "Case sensitive",
    "mode": "Mode",
    "count": "Count",
    "digits": "Digits",
    "characters": "User defined",
    "width": "Pad to length",
    "step": "Step",
    "pattern": "Expression",
    "match": "Matching text",
}
MULTILINE = {"alphabet", "script", "names", "mapping"}
SIGNED = {"step", "start", "years", "months", "days", "hours", "minutes", "seconds", "milliseconds"}


def defaults_for(rule):
    if rule.behavior == "renamer":
        return REGISTRY[rule.kind].defaults
    from .rules import RULE_DEFAULTS

    return RULE_DEFAULTS[rule.kind]


def effective_options(rule):
    options = defaults_for(rule) | rule.options
    if rule.behavior == "renamer":
        for flag, text in OPTION_SWITCHES.get(rule.kind, {}).items():
            if flag not in rule.options:
                options[flag] = bool(options[text])
        if rule.kind == "date" and "adjust_time" not in rule.options:
            options["adjust_time"] = any(
                options[key] for key in ("years", "months", "days", "hours", "minutes", "seconds", "milliseconds")
            )
    return options


def validate(rule):
    if rule.kind not in REGISTRY:
        raise ValueError("Unknown ReNamer rule")
    d = REGISTRY[rule.kind]
    if set(rule.options) - set(d.defaults):
        raise ValueError("Unknown rule option")
    for key, value in rule.options.items():
        if type(value) is not type(d.defaults[key]):
            raise ValueError(f"Invalid value for {key}")
        if isinstance(value, str) and len(value) > (1048576 if key in MULTILINE else 8192):
            raise ValueError(f"{key} is too long")
        if type(value) is int and (abs(value) > 1000000 or key not in SIGNED and value < 0):
            raise ValueError(f"{key} is out of range")
        if key in d.choices and value not in d.choices[key]:
            raise ValueError(f"Invalid {key}")
    o = effective_options(rule)
    if rule.kind == "number" and o["repeat"] < 1:
        raise ValueError("Repeat must be at least 1")
    for key in ("length", "width", "count"):
        if key in o and o[key] > 32768:
            raise ValueError(f"{key} exceeds the maximum filename length")
    if rule.kind == "randomize":
        if not (o["digits"] or o["english"] or o["use_characters"] and o["characters"]) or o["length"] < 1:
            raise ValueError("Choose random characters and a positive length")
    if rule.kind == "translit":
        for line in o["alphabet"].splitlines():
            if line and ("=" not in line or not all(line.split("=", 1))):
                raise ValueError("Alphabet pairs must have nonempty sides separated by =")
    if rule.kind == "strip":
        if o["use_unicode_range"]:
            ranges(o["unicode_range"])
    if rule.kind == "date":
        for key in ("short_months", "long_months"):
            if o["use_" + key] and len(o[key].split(",")) != 12:
                raise ValueError("Custom months must contain 12 comma-separated names")


def ranges(text):
    result = []
    for part in filter(None, text.split(",")):
        ends = part.strip().split("-")
        try:
            lo, hi = int(ends[0], 16), int(ends[-1], 16)
        except ValueError as exc:
            raise ValueError("Invalid hexadecimal Unicode range") from exc
        if len(ends) > 2 or not 0 <= lo <= hi <= 0x10FFFF:
            raise ValueError("Invalid Unicode range")
        result.append((lo, hi))
    return result
