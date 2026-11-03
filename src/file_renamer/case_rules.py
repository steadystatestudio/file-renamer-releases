"""Word-aware title casing shared by current and saved legacy Case rules."""
from __future__ import annotations

import re


def title_case(value: str, *, preserve: bool = False, legacy: bool = False) -> str:
    """Keep straight and curly intra-word apostrophes inside a word.

    Legacy presets retain their original letter-only word boundaries; current
    rules retain their existing digit/underscore word boundaries. An opening or
    closing quotation mark still separates words.
    """
    if legacy:
        # str.title() also treats digits and underscores as boundaries. Apply it
        # to each apostrophe-free part only when starting a new whole word.
        pattern = r"[^\W\d_]+(?:['’][^\W\d_]+)*"
        return re.sub(pattern, lambda match: match[0].capitalize(), value)
    base = value if preserve else value.lower()
    return re.sub(r"\w+(?:['’]\w+)*", lambda match: match[0][:1].upper() + match[0][1:], base)
