"""Pure filename transformations. No filesystem or GUI access."""
from __future__ import annotations

import os
import re
import string
import unicodedata

from .filename_policy import repair_filename
from .models import RuleSpec
from .registry import REGISTRY

RULE_DEFAULTS = {
    "insert": {"text": "", "position": "prefix", "index": 0,
               "match": "", "occurrence": "first", "case_sensitive": True},
    "delete": {"start": 0, "count": 1, "mode": "position", "from_right": False,
               "delimiter": "", "end_delimiter": "", "include_delimiters": False},
    "remove": {"text": "", "case_sensitive": True, "all": True, "occurrence": "legacy"},
    "replace": {"find": "", "replacement": "", "case_sensitive": True, "all": True, "occurrence": "legacy"},
    "case": {"mode": "lower"},
    "extension": {"text": "jpg"},
    "number": {"start": 1, "step": 1, "width": 3, "position": "prefix", "separator": "_", "per_folder": False},
    "padding": {"width": 3},
    "cleanup": {"trim": True, "collapse": True, "separator": " "},
    "regex": {"pattern": "", "replacement": "", "case_sensitive": True, "all": True},
}
RULE_DEFAULTS.update({
    "strip": {"digits": False, "whitespace": False, "punctuation": False, "symbols": False, "characters": ""},
    "accents": {},
    "rearrange": {"delimiter": "_", "template": "{2}_{1}"},
    "repair": {"platform": "This computer"},
})
# Presentation order follows ReNamer; identifiers remain stable for saved presets.
RULE_LABELS = {
    "insert": "Insert", "delete": "Delete", "remove": "Remove",
    "replace": "Replace", "rearrange": "Rearrange", "extension": "Extension",
    "strip": "Strip", "case": "Case", "number": "Serialize", "padding": "Padding",
    "cleanup": "Clean Up", "accents": "Translit", "regex": "Regular Expressions",
    "repair": "Repair filename",
}
RULE_LABELS.update({key: value.label for key, value in REGISTRY.items()})
RULE_ORDER = (*REGISTRY, "repair")
CHOICES = {
    "insert": {"position": ("prefix", "suffix", "index", "before", "after"), "occurrence": ("first", "last")},
    "delete": {"mode": ("position", "before", "after", "between")},
    "case": {"mode": ("lower", "upper", "title", "sentence", "swap")},
    "number": {"position": ("prefix", "suffix")},
    "remove": {"occurrence": ("legacy", "first", "last", "all")},
    "replace": {"occurrence": ("legacy", "first", "last", "all")},
    "repair": {"platform": ("This computer", "Windows-compatible")},
}
def validate_rule(rule: RuleSpec) -> None:
    if not isinstance(rule.kind, str) or not isinstance(rule.target, str):
        raise ValueError("Rule type and target must be text")
    if rule.behavior not in {"legacy", "renamer"}:
        raise ValueError("Unknown rule behavior")
    if rule.behavior == "renamer":
        from .registry import validate
        if rule.target not in {"stem", "extension", "name"}:
            raise ValueError("Unknown target")
        validate(rule)
        return
    if rule.kind not in RULE_DEFAULTS or rule.target not in {"stem", "extension", "name"}:
        raise ValueError("Unknown rule type or target")
    defaults = RULE_DEFAULTS[rule.kind]
    if set(rule.options) - set(defaults):
        raise ValueError("Unknown rule option")
    for key, value in rule.options.items():
        if type(value) is not type(defaults[key]):
            raise ValueError(f"Invalid value for {key}")
        if isinstance(value, str) and len(value) > 8192:
            raise ValueError(f"{key} is too long (maximum 8192 characters)")
        if key in CHOICES.get(rule.kind, {}) and value not in CHOICES[rule.kind][key]:
            raise ValueError(f"Invalid {key}")
        if type(value) is int:
            limit = 255 if key == "width" else 1_000_000
            if abs(value) > limit or (key in {"width", "count", "start", "index"} and value < 0):
                raise ValueError(f"{key} is out of range")
    if rule.kind == "number" and rule.options.get("position") == "index":
        raise ValueError("Numbering supports prefix or suffix")


def split_name(name: str) -> tuple[str, str]:
    at = name.rfind(".")
    return (name[:at], name[at + 1:]) if 0 < at < len(name) - 1 and name[:at].strip(".") else (name, "")


def rearrange(value: str, delimiter: str, template: str) -> str:
    if not delimiter:
        raise ValueError("Enter a delimiter")
    parts = value.split(delimiter)
    result = []
    for literal, field, spec, conversion in string.Formatter().parse(template):
        result.append(literal)
        if field is not None:
            if not field.isascii() or not field.isdigit() or spec or conversion:
                raise ValueError("Use numbered parts such as {2}_{1}; double braces for literal braces")
            index = int(field)
            if not 1 <= index <= len(parts):
                raise ValueError(f"Filename has no part {index}")
            result.append(parts[index - 1])
    return "".join(result)


def remove_accents(value: str) -> str:
    result, latin = [], False
    for char in unicodedata.normalize("NFD", value):
        if unicodedata.category(char).startswith("M"):
            if not latin:
                result.append(char)
        else:
            latin = "LATIN" in unicodedata.name(char, "")
            result.append(char)
    return unicodedata.normalize("NFC", "".join(result))



def apply_rule(name: str, rule: RuleSpec, index: int, context=None) -> str:
    validate_rule(rule)
    if not rule.enabled:
        return name
    if rule.behavior == "renamer":
        from .compat_rules import Evaluation, apply
        return apply(name, rule, context or Evaluation(index=index))
    options = RULE_DEFAULTS[rule.kind] | rule.options
    stem, extension = split_name(name)
    value = {"stem": stem, "extension": extension, "name": name}[rule.target]
    kind = rule.kind
    if kind == "repair":
        return repair_filename(name, options["platform"] == "Windows-compatible" or os.name == "nt")
    if kind == "extension":
        new_extension = options["text"].lstrip(".")
        return stem + ("." + new_extension if new_extension else "")
    if kind == "insert":
        position = options["position"]
        at = 0 if position == "prefix" else len(value) if position == "suffix" else options["index"]
        if position in {"before", "after"}:
            if not options["match"]:
                raise ValueError("Enter text to insert before or after")
            matches = list(re.finditer(re.escape(options["match"]), value,
                                      0 if options["case_sensitive"] else re.IGNORECASE))
            if not matches:
                return name
            match = matches[0 if options["occurrence"] == "first" else -1]
            at = match.start() if position == "before" else match.end()
        value = value[:at] + options["text"] + value[at:]
    elif kind == "delete":
        mode = options["mode"]
        if mode == "position":
            at = options["start"]
            end = at + options["count"]
            if options["from_right"]:
                end = max(0, len(value) - at)
                at = max(0, end - options["count"])
        else:
            delimiter = options["delimiter"]
            if not delimiter:
                raise ValueError("Enter a delimiter")
            found = value.find(delimiter)
            if found < 0:
                return name
            include = options["include_delimiters"]
            if mode == "before":
                at, end = 0, found + (len(delimiter) if include else 0)
            elif mode == "after":
                at, end = found + (0 if include else len(delimiter)), len(value)
            else:
                other = options["end_delimiter"]
                if not other:
                    raise ValueError("Enter an end delimiter")
                finish = value.find(other, found + len(delimiter))
                if finish < 0:
                    return name
                at = found + (0 if include else len(delimiter))
                end = finish + (len(other) if include else 0)
        value = value[:at] + value[end:]
    elif kind in {"replace", "remove", "regex"}:
        pattern = options["pattern"] if kind == "regex" else options["find" if kind == "replace" else "text"]
        replacement = "" if kind == "remove" else options["replacement"]
        if not pattern:
            raise ValueError("Enter a search pattern or text")
        count = 0 if options["all"] else 1
        flags = 0 if options["case_sensitive"] else re.IGNORECASE
        if kind == "regex":
            value = re.sub(pattern, replacement, value, count=count, flags=flags)
        else:
            occurrence = options["occurrence"]
            if occurrence == "last":
                matches = list(re.finditer(re.escape(pattern), value, flags))
                if matches:
                    match = matches[-1]
                    value = value[:match.start()] + replacement + value[match.end():]
            else:
                count = count if occurrence == "legacy" else 0 if occurrence == "all" else 1
                value = re.sub(re.escape(pattern), lambda _: replacement, value, count=count, flags=flags)
    elif kind == "case":
        value = {"lower": str.lower, "upper": str.upper, "title": str.title,
                 "sentence": str.capitalize, "swap": str.swapcase}[options["mode"]](value)
    elif kind == "number":
        number = str(options["start"] + index * options["step"]).zfill(options["width"])
        value = (number + options["separator"] + value if options["position"] == "prefix"
                 else value + options["separator"] + number)
    elif kind == "padding":
        value = re.sub(r"\d+", lambda match: match[0].lstrip("0").zfill(options["width"]) or "0", value)
    elif kind == "cleanup":
        if options["collapse"]:
            value = re.sub(r"[\s_-]+", lambda _: options["separator"], value)
        if options["trim"]:
            value = value.strip(" \t\r\n_-" + options["separator"])
    elif kind == "strip":
        value = "".join(c for c in value if not (
            c in options["characters"] or (options["digits"] and unicodedata.category(c) == "Nd")
            or (options["whitespace"] and c.isspace())
            or (options["punctuation"] and unicodedata.category(c).startswith("P"))
            or (options["symbols"] and unicodedata.category(c).startswith("S"))))
    elif kind == "accents":
        value = remove_accents(value)
    elif kind == "rearrange":
        value = rearrange(value, options["delimiter"], options["template"])
    if rule.target == "name":
        return value
    if rule.target == "stem":
        return value + ("." + extension if extension else "")
    return stem + ("." + value if value else "")


def rule_details(rule: RuleSpec) -> str:
    if rule.behavior == "renamer":
        from .registry import REGISTRY
        o = REGISTRY[rule.kind].defaults | rule.options
        return "; ".join(f"{key.replace('_', ' ')}: {str(value)[:100]}" for key, value in o.items()
                         if key != "skip_extension" and value not in ("", False)) or "No options selected"
    o = RULE_DEFAULTS[rule.kind] | rule.options
    kind = rule.kind
    if kind == "case":
        return o["mode"].capitalize()
    if kind == "number":
        return f"Start {o['start']}, step {o['step']}, {o['width']} digits; {o['position']}"
    if kind == "insert":
        where = f"{o['position']} {o['match']!r}" if o["position"] in {"before", "after"} else o["position"]
        if o["position"] == "index":
            where = f"position {o['index']}"
        return f"{o['text']!r} at {where}"
    if kind in {"remove", "replace", "regex"}:
        find = o.get("find", o.get("pattern", o.get("text")))
        occurrence = o.get("occurrence", "legacy")
        if occurrence == "legacy":
            occurrence = "all" if o["all"] else "first"
        return f"{find!r} to {o.get('replacement', '')!r}; {occurrence} match(es)"
    if kind == "extension":
        return f"Change to {o['text']!r}" if o["text"] else "Remove extension"
    if kind == "delete":
        if o["mode"] == "position":
            return f"{o['count']} characters at {o['start']} from the {'right' if o['from_right'] else 'left'}"
        return f"{o['mode'].capitalize()} {o['delimiter']!r}" + (
            f" and {o['end_delimiter']!r}" if o["mode"] == "between" else "")
    if kind == "padding":
        return f"At least {o['width']} digits"
    if kind == "cleanup":
        return "; ".join(text for enabled, text in ((o["trim"], "Trim edges"),
                           (o["collapse"], f"Combine separators using {o['separator']!r}")) if enabled) or "No changes"
    if kind == "strip":
        sets = [key for key in ("digits", "whitespace", "punctuation", "symbols") if o[key]]
        if o["characters"]:
            sets.append(repr(o["characters"]))
        return "Remove " + ", ".join(sets) if sets else "No characters selected"
    if kind == "accents":
        return "Remove Latin accents; preserve other scripts"
    if kind == "rearrange":
        return f"Split on {o['delimiter']!r}; arrange as {o['template']}"
    return o["platform"]


def rule_summary(rule: RuleSpec) -> str:
    target = "extension" if rule.kind == "extension" else "name" if rule.kind == "repair" else rule.target
    return f"{RULE_LABELS[rule.kind]} - {rule_details(rule)} - {target}"
