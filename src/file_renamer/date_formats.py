"""Delphi-style date parsing/formatting used by Reformat Date and metadata."""

import calendar
import re
from datetime import datetime, timedelta

TOKENS = re.compile(r"am/pm|a/p|yyyy|mmmm|dddd|mmm|ddd|zzz|yy|mm|dd|hh|nn|ss|zz|m|d|h|n|s|z|c|t+", re.I)


def pieces(fmt):
    # Quoted literals do not interpret format tokens.
    result, pos, previous = [], 0, ""
    while pos < len(fmt):
        if fmt[pos] in "\"'":
            quote = fmt[pos]
            end = fmt.find(quote, pos + 1)
            if end < 0:
                raise ValueError("Unclosed date-format quote")
            result.append((False, fmt[pos + 1 : end]))
            pos = end + 1
        else:
            match = TOKENS.match(fmt, pos)
            if match:
                token = match[0].lower()
                if token in {"m", "mm"} and previous in {"h", "hh"}:
                    token = "n" if token == "m" else "nn"
                result.append((True, token))
                previous = token
                pos = match.end()
            else:
                result.append((False, fmt[pos]))
                pos += 1
    return result


def month_names(options):
    short = (
        options.get("short_months", "").split(",")
        if options.get("short_months") and options.get("use_short_months", True)
        else list(calendar.month_abbr)[1:]
    )
    long = (
        options.get("long_months", "").split(",")
        if options.get("long_months") and options.get("use_long_months", True)
        else list(calendar.month_name)[1:]
    )
    return short, long


def format_date(value, fmt, options=None):
    options = options or {}
    short, long = month_names(options)
    hour = value.hour % 12 or 12 if any(t in fmt.lower() for t in ("am/pm", "a/p")) else value.hour
    values = {
        "yyyy": f"{value.year:04}",
        "yy": f"{value.year % 100:02}",
        "m": str(value.month),
        "mm": f"{value.month:02}",
        "mmm": short[value.month - 1],
        "mmmm": long[value.month - 1],
        "d": str(value.day),
        "dd": f"{value.day:02}",
        "ddd": calendar.day_abbr[value.weekday()],
        "dddd": calendar.day_name[value.weekday()],
        "h": str(hour),
        "hh": f"{hour:02}",
        "n": str(value.minute),
        "nn": f"{value.minute:02}",
        "s": str(value.second),
        "ss": f"{value.second:02}",
        "z": str(value.microsecond // 1000),
        "zz": f"{value.microsecond // 1000:02}",
        "zzz": f"{value.microsecond // 1000:03}",
        "am/pm": "AM" if value.hour < 12 else "PM",
        "a/p": "A" if value.hour < 12 else "P",
        "c": value.strftime("%x %X"),
        "t": value.strftime("%H:%M"),
        "tt": value.strftime("%X"),
    }
    return "".join(values.get(text, text) if token else text for token, text in pieces(fmt))


def reformat(text, options, now=None):
    now = now or datetime.now()
    if not options.get("adjust_time", True):
        options = options | dict.fromkeys(("years", "months", "days", "hours", "minutes", "seconds", "milliseconds"), 0)
    short, long = month_names(options)
    fields = {
        "yyyy": ("year", r"\d{4}"),
        "yy": ("year2", r"\d{2}"),
        "m": ("month", r"\d{1,2}"),
        "mm": ("month", r"\d{2}"),
        "d": ("day", r"\d{1,2}"),
        "dd": ("day", r"\d{2}"),
        "h": ("hour", r"\d{1,2}"),
        "hh": ("hour", r"\d{2}"),
        "n": ("minute", r"\d{1,2}"),
        "nn": ("minute", r"\d{2}"),
        "s": ("second", r"\d{1,2}"),
        "ss": ("second", r"\d{2}"),
        "z": ("ms", r"\d{1,3}"),
        "zz": ("ms", r"\d{2,3}"),
        "zzz": ("ms", r"\d{3}"),
        "mmm": ("short", "|".join(map(re.escape, short))),
        "mmmm": ("long", "|".join(map(re.escape, long))),
        "am/pm": ("ampm", "AM|PM"),
        "a/p": ("ampm", "A|P"),
        "ddd": ("weekday", "|".join(map(re.escape, calendar.day_abbr))),
        "dddd": ("weekday", "|".join(map(re.escape, calendar.day_name))),
    }
    patterns = []
    for fmt in options["find_formats"].split("|"):
        pattern, seen = "", set()
        for token, part in pieces(fmt):
            if token and part in fields:
                key, expression = fields[part]
                if key in seen:
                    raise ValueError("Repeated date-format field")
                seen.add(key)
                pattern += f"(?P<{key}>{expression})"
            else:
                pattern += re.escape(part)
        if not seen:
            raise ValueError("Input format must contain date or time fields")
        if options["whole_words"]:
            pattern = r"\b" + pattern + r"\b"
        patterns.append(re.compile(pattern, re.I))
    # Match against the original input once; never reinterpret the replacement as a new date.
    candidates = []
    for priority, pattern in enumerate(patterns):
        for match in pattern.finditer(text):
            d = match.groupdict()
            try:
                year = int(d.get("year") or now.year)
                if d.get("year2"):
                    n = int(d["year2"])
                    year = 2000 + n if n < 50 else 1900 + n
                month = int(d.get("month") or 1)
                for key, names in (("short", short), ("long", long)):
                    if d.get(key):
                        month = [s.casefold() for s in names].index(d[key].casefold()) + 1
                hour = int(d.get("hour") or 0)
                if d.get("ampm"):
                    if not 1 <= hour <= 12:
                        continue
                    hour = hour % 12 + (12 if d["ampm"].upper().startswith("P") else 0)
                value = datetime(
                    year,
                    month,
                    int(d.get("day") or 1),
                    hour,
                    int(d.get("minute") or 0),
                    int(d.get("second") or 0),
                    int(d.get("ms") or 0) * 1000,
                )
                months = value.year * 12 + value.month - 1 + options["years"] * 12 + options["months"]
                y, m = divmod(months, 12)
                value = value.replace(year=y, month=m + 1, day=min(value.day, calendar.monthrange(y, m + 1)[1]))
                value += timedelta(
                    days=options["days"],
                    hours=options["hours"],
                    minutes=options["minutes"],
                    seconds=options["seconds"],
                    milliseconds=options["milliseconds"],
                )
                candidates.append(
                    (match.start(), priority, match.end(), format_date(value, options["format"], options))
                )
            except (ValueError, OverflowError):
                continue
    out, end = [], 0
    for start, _, finish, replacement in sorted(candidates):
        if start < end:
            continue
        out.extend((text[end:start], replacement))
        end = finish
    out.append(text[end:])
    return "".join(out)
