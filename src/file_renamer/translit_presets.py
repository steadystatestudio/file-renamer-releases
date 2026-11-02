"""Editable alphabets built from Unicode normalization and standard letter pairs."""

import unicodedata


def pairs(source, targets):
    return "\n".join(f"{char}={target}" for char, target in zip(source, targets.split("|")) if target)


def alphabets():
    latin = []
    for code in range(0x00C0, 0x0250):
        char = chr(code)
        plain = "".join(c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c))
        if plain != char and plain.isascii() and plain.isalpha() and char.islower():
            latin.append(f"{char}={plain}")
    return {
        "Latin accents": "\n".join(latin) + "\nß=ss\næ=ae\nœ=oe\nø=o\nł=l\nđ=d",
        "German": "ä=ae\nö=oe\nü=ue\nß=ss",
        "French": "é=e\nè=e\nê=e\në=e\nà=a\nâ=a\nç=c\nœ=oe\nù=u\nû=u\nî=i\nï=i\nô=o",
        "Greek": pairs("αβγδεζηθικλμνξοπρσςτυφχψω", "a|v|g|d|e|z|i|th|i|k|l|m|n|x|o|p|r|s|s|t|y|f|ch|ps|o"),
        "Russian": pairs(
            "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
            "a|b|v|g|d|e|yo|zh|z|i|y|k|l|m|n|o|p|r|s|t|u|f|kh|ts|ch|sh|shch||y||e|yu|ya",
        ),
        "Ukrainian": pairs(
            "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя",
            "a|b|v|h|g|d|e|ye|zh|z|y|i|yi|y|k|l|m|n|o|p|r|s|t|u|f|kh|ts|ch|sh|shch||yu|ya",
        ),
    }
