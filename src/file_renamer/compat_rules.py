"""Batch-aware ReNamer conventions, independently implemented."""

import csv
import io
import math
import random
import re
import string
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from .date_formats import reformat
from .registry import effective_options, ranges


@dataclass
class Evaluation:
    path: str = ""
    index: int = 0
    rule_index: int = 0
    state: dict = field(default_factory=dict)
    now: datetime = field(default_factory=datetime.now)
    clipboard: str = ""
    metadata: object = None
    pascal: dict = field(default_factory=dict)
    files: tuple = ()
    marked_files: tuple = ()
    file_index: int = 0
    globals: dict = field(default_factory=dict)
    application_path: str = ""
    application_params: tuple = ()

    def expand(self, text):
        if re.search(r":[A-Za-z][A-Za-z0-9_]*:", text):
            if self.metadata is None:
                from .metadata import Metadata

                self.metadata = Metadata(self.now, self.clipboard)
            return self.metadata.expand(text, self.path)
        return text


def put(value, text, o):
    mode = o["position"]
    at = 0 if mode == "prefix" else len(value) if mode == "suffix" else max(0, o.get("index", 1) - 1)
    if mode == "replace":
        return text
    if o.get("from_right"):
        at = max(0, len(value) - at)
    if mode in {"before", "after"}:
        if not o["match"]:
            raise ValueError("Enter matching text")
        at = value.find(o["match"])
        if at < 0:
            return value
        if mode == "after":
            at += len(o["match"])
    return value[:at] + text + value[at:]


def wildcard(pattern):
    out, n, i = "", 0, 0
    while i < len(pattern):
        c = pattern[i]
        if c in "*?":
            n += 1
            out += "(.*)" if c == "*" else "(.)"
        elif c == "[" and "]" in pattern[i + 1 :]:
            end = pattern.index("]", i + 1)
            out += pattern[i : end + 1]
            i = end
        else:
            out += re.escape(c)
        i += 1
    return out


def substitute(pattern, replacement, value, o, regex=False, context=None):
    expression = pattern if regex else wildcard(pattern) if o["wildcards"] else re.escape(pattern)
    if not pattern:
        raise ValueError("Enter search text or expression")
    if o.get("whole_words"):
        expression = r"\b(?:" + expression + r")\b"
    # ReNamer supports \x{NNNN} Unicode escapes and its dollar backreferences.
    expression = re.sub(r"\\x\{([0-9a-fA-F]+)\}", lambda m: re.escape(chr(int(m[1], 16))), expression)
    expression = expression.replace(r"\z", r"\Z")
    if regex and context is not None:
        from .pascal import PascalSession

        if "regex" not in context.pascal:
            context.pascal["regex"] = PascalSession()
        matches = context.pascal["regex"].matches(expression, value, o["case_sensitive"])
        encoded = value.encode("utf-16-le")
        for match in reversed(matches):
            start = len(encoded[: match["start"] * 2].decode("utf-16-le"))
            end = len(encoded[: (match["start"] + match["length"]) * 2].decode("utf-16-le"))
            groups = match["groups"]
            result = re.sub(
                r"\$\$|\$(\d+)",
                lambda m: "$" if m[0] == "$$" else groups[int(m[1])] if int(m[1]) < len(groups) else "",
                replacement,
            )
            value = value[:start] + result + value[end:]
        return value
    matches = list(re.finditer(expression, value, 0 if o["case_sensitive"] else re.I))
    if o.get("wildcards") and not regex:
        matches = [match for match in matches if match.start() != match.end()]
    occurrence = o.get("occurrence", "all")
    if occurrence == "first":
        matches = matches[:1]
    elif occurrence == "last":
        matches = matches[-1:]

    def render(match):
        if not (regex or o.get("wildcards")):
            return replacement

        def group(m):
            if m[0] == "$$":
                return "$"
            number = int(m[1])
            return (match[number] or "") if number <= len(match.groups()) else ""

        return re.sub(r"\$\$|\$(\d+)", group, replacement)

    for match in reversed(matches):
        value = value[: match.start()] + render(match) + value[match.end() :]
    return value


def roman(n):
    if n <= 0:
        raise ValueError("Roman numbers require a positive index")
    out = ""
    for value, token in (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ):
        count, n = divmod(n, value)
        out += token * count
    return out


def numbered(n, o):
    system = o["system"]
    if system == "roman":
        return roman(n)
    if system == "music":
        if n < 1:
            raise ValueError("Music notes require index >= 1")
        octave, note = divmod(n - 1, 12)
        return ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")[note] + str(octave)
    if system == "chinese":
        if not 0 <= n <= 999999999:
            raise ValueError("Chinese index is out of range")
        if n == 0:
            return "零"
        digits = "零一二三四五六七八九"
        if n < 10000:
            result, pending_zero = "", False
            for i, c in enumerate(str(n)):
                if c == "0":
                    pending_zero = bool(result)
                    continue
                if pending_zero:
                    result += digits[0]
                    pending_zero = False
                result += digits[int(c)] + ("", "十", "百", "千")[len(str(n)) - i - 1]
            return result
        return numbered(n // 10000, o) + "万" + (numbered(n % 10000, o) if n % 10000 else "")
    if system == "decimal":
        return str(n).zfill(o["width"] if o["pad"] else 0)
    symbols = "abcdefghijklmnopqrstuvwxyz" if system == "letters" else o["symbols"]
    if len(symbols) < 2 or len(set(symbols)) != len(symbols):
        raise ValueError("Numbering alphabet needs at least two distinct characters")
    if system in {"letters", "custom_alphabetic"}:
        n -= 1
    if n < 0:
        raise ValueError("Index is too small for this numbering system")
    result = symbols[n % len(symbols)]
    n //= len(symbols)
    while n:
        result = symbols[n % len(symbols)] + result
        n //= len(symbols)
    return result.rjust(o["width"] if o["pad"] else 0, symbols[0])


def mapping_rows(text):
    if not text:
        return []
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if any(len(row) != 2 for row in rows):
        raise ValueError("Each mapping row needs Match and New name")
    return rows


def apply(name, rule, context):
    from .rules import split_name

    o = effective_options(rule)
    kind = rule.kind
    stem, ext = split_name(name)
    value = stem if o.get("skip_extension", False) else name
    state = context.state.setdefault(context.rule_index, {})
    if kind == "insert":
        value = put(value, context.expand(o["text"]), o)
    elif kind == "delete":
        if o["delete_current"]:
            value = ""
        else:
            subject = value[::-1] if o["from_right"] else value
            first, last = o["delimiter"], o["end_delimiter"]
            if o["from_right"]:
                first, last = first[::-1], last[::-1]
            at = max(0, o["start"] - 1)
            if o["from_mode"] == "delimiter":
                if not first:
                    raise ValueError("Enter From delimiter")
                at = subject.find(first)
                if at < 0:
                    return name
                if o["keep_delimiters"]:
                    at += len(first)
            end = at + o["count"] if o["until_mode"] == "count" else len(subject)
            if o["until_mode"] == "delimiter":
                if not last:
                    raise ValueError("Enter Until delimiter")
                end = subject.find(
                    last, at + (len(first) if o["from_mode"] == "delimiter" and not o["keep_delimiters"] else 0)
                )
                if end < 0:
                    return name
                if not o["keep_delimiters"]:
                    end += len(last)
            subject = subject[:at] + subject[end:]
            value = subject[::-1] if o["from_right"] else subject
    elif kind in {"remove", "replace", "regex"}:
        patterns = [o["pattern"]] if kind == "regex" else o["text" if kind == "remove" else "find"].split("*|*")
        replacements = (
            [""] if kind == "remove" else o["replacement"].split("*|*") if kind == "replace" else [o["replacement"]]
        )
        for i, pattern in enumerate(patterns):
            replacement = (
                replacements[i] if i < len(replacements) else replacements[0] if len(replacements) == 1 else ""
            )
            value = substitute(pattern, context.expand(replacement), value, o, kind == "regex", context)
    elif kind == "rearrange":
        separator = "*|*" if o["split_mode"] == "positions" and "*|*" in o["delimiter"] else "|"
        separators = o["delimiter"].split(separator)
        subject = value[::-1] if o["from_right"] else value
        if o["split_mode"] == "positions":
            positions = [0] + [max(0, min(len(subject), int(s) - 1)) for s in separators if s] + [len(subject)]
            if positions != sorted(positions):
                raise ValueError("Split positions must be increasing")
            parts = [subject[a:b] for a, b in zip(positions, positions[1:])]
        elif o["split_mode"] == "exact":
            parts = []
            for sep in separators:
                if not sep:
                    raise ValueError("Enter split delimiters")
                pos = subject.find(sep[::-1] if o["from_right"] else sep)
                if pos < 0:
                    return name
                parts.append(subject[:pos])
                subject = subject[pos + len(sep) :]
            parts.append(subject)
        else:
            if not any(separators):
                parts = [subject]
            else:
                parts = re.split(
                    "|".join(re.escape(s[::-1] if o["from_right"] else s) for s in separators if s), subject
                )
        if o["from_right"]:
            parts = [p[::-1] for p in parts]

        def part(m):
            i = int(m[1])
            if i == 0:
                return value
            index = i - 1 if i > 0 else i
            return parts[index] if -len(parts) <= index < len(parts) else ""

        value = context.expand(re.sub(r"\$(-?\d+)", part, o["template"]))
    elif kind == "extension":
        if o["detect"]:
            if context.metadata is None:
                from .metadata import Metadata

                context.metadata = Metadata(context.now, context.clipboard)
            new = context.metadata.get("BinarySign_Extension", context.path)
            if not new:
                return name
        else:
            new = o["text"].lstrip(".")
        result = name
        if o["change"] or o["detect"]:
            result = (name if o["append"] else stem) + ("." + new if new else "")
        if o["remove_duplicates"]:
            while True:
                base, extension = split_name(result)
                inner, prior = split_name(base)
                if not prior or (
                    prior != extension if o["case_sensitive"] else prior.casefold() != extension.casefold()
                ):
                    break
                result = inner + "." + extension
        return result
    elif kind == "strip":
        chars = (o["characters"] if o["use_characters"] else "") + (string.ascii_letters if o["english"] else "")
        chars += string.digits if o["digits"] else ""
        chars += "!\"#$%&'*+,-./:;=?@^_`|~" if o["symbols"] else ""
        chars += "(){}[]<>" if o["brackets"] else ""
        spans = ranges(o["unicode_range"]) if o["use_unicode_range"] else []
        if not o["case_sensitive"]:
            chars = {c.casefold() for c in chars}

        def selected(c):
            match = (c if o["case_sensitive"] else c.casefold()) in chars or any(a <= ord(c) <= b for a, b in spans)
            return not match if o["invert"] else match

        if o["position"] == "everywhere":
            value = "".join(c for c in value if not selected(c))
        else:
            seq = value[::-1] if o["position"] == "trailing" else value
            i = 0
            while i < len(seq) and selected(seq[i]):
                i += 1
            value = seq[i:][::-1] if o["position"] == "trailing" else seq[i:]
    elif kind == "case":
        base = value if o["preserve"] else value.lower()
        mode = o["mode"]
        if mode == "title":
            value = re.sub(r"\b\w", lambda m: m[0].upper(), base)
        elif mode == "first":
            value = base[:1].upper() + base[1:]
        elif mode == "sentence":
            value = re.sub(r"(^|[.!?]\s+)(\w)", lambda m: m[1] + m[2].upper(), base)
        elif mode != "none":
            value = {"lower": str.lower, "upper": str.upper, "swap": str.swapcase}[mode](value)
        for fragment in filter(None, o["fragments"].split(",") if o["force_fragments"] else ()):
            value = re.sub(re.escape(fragment), lambda _: fragment, value, flags=re.I)
        if o["skip_extension"] and o["extension_case"] != "unchanged":
            ext = getattr(ext, o["extension_case"])()
        elif not o["skip_extension"] and o["extension_case"] != "unchanged":
            base, suffix = split_name(value)
            value = base + ("." + getattr(suffix, o["extension_case"])() if suffix else "")
    elif kind == "number":
        folder = str(__import__("pathlib").Path(context.path).parent)
        reset = o["reset_folder"] and state.get("folder", folder) != folder
        reset |= o["reset_name"] and state.get("name", name) != name
        count = state.get("count", 0)
        if reset or o["reset_every"] and count >= o["reset_every"]:
            count = 0
        number = o["start"] + count // o["repeat"] * o["step"]
        state.update(count=count + 1, folder=folder, name=name)
        value = put(value, numbered(number, o), o)
    elif kind == "randomize":
        alphabet = "".join(
            dict.fromkeys(
                (string.digits if o["digits"] else "")
                + (string.ascii_lowercase if o["english"] else "")
                + (o["characters"] if o["use_characters"] else "")
            )
        )
        if not alphabet or not o["length"]:
            raise ValueError("Choose characters and a positive random length")
        used = state.setdefault("used", set())
        capacity = len(alphabet) ** o["length"]
        rng = state.setdefault("rng", random.Random())
        # Sampling unused indices avoids unbounded collision retries.
        number = rng.randrange(capacity)
        if o["unique"] and len(used) < capacity:
            while number in used:
                number = (number + 1) % capacity
            used.add(number)
        seq = ""
        for _ in range(o["length"]):
            number, digit = divmod(number, len(alphabet))
            seq += alphabet[digit]
        value = put(value, seq, o)
    elif kind == "padding":
        if o["remove_zeros"]:
            value = re.sub(r"[0-9]+", lambda m: m[0].lstrip("0") or "0", value)
        if o["pad_numbers"]:
            value = re.sub(r"[0-9]+", lambda m: m[0].zfill(o["width"]), value)
        if o["pad_text"]:
            if not o["characters"]:
                raise ValueError("Enter padding characters")
            count = max(0, o["length"] - len(value))
            pad = (o["characters"] * math.ceil(count / len(o["characters"])))[:count]
            value = pad + value if o["position"] == "left" else value + pad
    elif kind == "cleanup":
        replacement_chars = o["replace_chars"] + "".join(
            char
            for key, char in (("space_underscore", "_"), ("space_dash", "-"), ("space_dot", "."), ("space_comma", ","))
            if o[key]
        )
        for key, left, right in (("round", "(", ")"), ("square", "[", "]"), ("curly", "{", "}")):
            if o[key]:
                # Repeat to remove nested bracket contents as well.
                pat = re.escape(left) + "[^" + re.escape(left + right) + "]*" + re.escape(right)
                while re.search(pat, value):
                    value = re.sub(pat, "", value)
        if replacement_chars:
            value = "".join(
                " "
                if c in replacement_chars
                and not (
                    o["skip_versions"]
                    and i > 0
                    and i < len(value) - 1
                    and value[i - 1].isdigit()
                    and value[i + 1].isdigit()
                )
                else c
                for i, c in enumerate(value)
            )
        if o["normalize_spaces"]:
            value = "".join(" " if c.isspace() else c for c in value)
        if o["strip_marks"]:
            value = unicodedata.normalize(
                "NFC",
                "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.category(c).startswith("M")),
            )
        if o["strip_emoji"]:
            value = re.sub("[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u200d]", "", value)
        if o["camel_case"]:
            value = re.sub(r"(?<=\S)(?=[A-Z])", " ", value)
        if o["fix_spaces"]:
            value = re.sub(" +", " ", value).strip(" ")
        if o["sharepoint"]:
            full = value + ("." + ext if o["skip_extension"] and ext else "")
            full = full.strip().replace("{", "(").replace("}", ")")
            full = re.sub(r"[\x00-\x1f/\\*?\"<>|:#%~&]|\.{2,}", "", full)
            return full
    elif kind == "translit":
        pairs = [line.split("=", 1) for line in o["alphabet"].splitlines() if line]
        if o["direction"] == "backward":
            pairs = [(b, a) for a, b in pairs]
        # Single left-to-right pass; generated text is never matched again.
        result, pos = [], 0
        while pos < len(value):
            for a, b in pairs:
                source = value[pos : pos + len(a)]
                if source.casefold() == a.casefold():
                    output = b.lower() if o["auto_case"] else b
                    if o["auto_case"] and source[0].isupper():
                        next_char = value[pos + len(a) : pos + len(a) + 1]
                        output = (
                            output.upper()
                            if len(output) == 1 or next_char.isupper()
                            else output[:1].upper() + output[1:]
                        )
                    result.append(output)
                    pos += len(a)
                    break
            else:
                result.append(value[pos])
                pos += 1
        value = "".join(result)
    elif kind == "date":
        value = reformat(value, o, context.now)
    elif kind == "pascal":
        if context.rule_index not in context.pascal:
            from .pascal import PascalSession

            context.pascal[context.rule_index] = PascalSession()
        return context.pascal[context.rule_index].evaluate(o["script"], name, context)
    elif kind == "userinput":
        names = o["names"].splitlines()
        if context.index < len(names):
            value = put(value, names[context.index], o)
    elif kind == "mapping":
        rows = state.setdefault("rows", mapping_rows(o["mapping"]))
        used = state.setdefault("used", set())
        for i, (old, new) in enumerate(rows):
            if not o["reuse"] and i in used:
                continue
            if o["inverse"]:
                old, new = new, old
            if not old:
                continue
            expression = re.escape(old) if o["partial"] else "^" + re.escape(old) + "$"
            match = re.search(expression, value, 0 if o["case_sensitive"] else re.I)
            if match:
                value = value[: match.start()] + new + value[match.end() :]
                used.add(i)
                break
    return value + ("." + ext if ext else "") if o.get("skip_extension", False) else value
