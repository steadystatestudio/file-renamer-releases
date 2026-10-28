"""Filename-only policies shared by preview and explicit repair rules."""
from __future__ import annotations

import os


def reserved_windows(name: str) -> bool:
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved |= {f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³"}
    return name.split(".")[0].rstrip().upper() in reserved


def invalid_character(char: str, windows: bool) -> bool:
    return char in "\x00/" or (windows and (ord(char) < 32 or char in '\\<>:"|?*'))


def filename_error(name: str, windows: bool | None = None) -> str:
    windows = os.name == "nt" if windows is None else windows
    if not name or name in {".", ".."}:
        return "Name must be a filename, not a path"
    if any(invalid_character(char, windows) for char in name):
        return "Invalid Windows filename" if windows else "Filename cannot contain NUL or /"
    if windows and name.endswith((" ", ".")):
        return "Windows filenames cannot end with a space or dot"
    if windows and reserved_windows(name):
        return "Reserved Windows filename"
    return ""


def repair_filename(name: str, windows: bool) -> str:
    name = "".join("_" if invalid_character(char, windows) else char for char in name)
    if windows:
        name = name.rstrip(" .")
        if reserved_windows(name):
            name = "_" + name
    return "_" if not name or name in {".", ".."} else name
