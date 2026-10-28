from __future__ import annotations

import ctypes
import os
import stat
import sys
from pathlib import Path

from .filename_policy import filename_error
from .models import FileEntry, FileIdentity


def linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def hidden_path(path: str | Path) -> bool:
    """Protect hidden leaves and ancestors without affecting recovery identity checks."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part == Path(part.anchor):
            continue  # Windows volume roots carry Hidden/System attributes.
        if part.name.startswith("."):
            return True
        info = part.lstat()
        if getattr(info, "st_file_attributes", 0) & 0x6:  # Windows Hidden or System
            return True
    return False


def regular_identity(path: str | Path) -> FileIdentity:
    path = Path(path)
    # Reject linked ancestors as well as linked leaves; never follow junctions.
    for part in (path, *path.parents):
        if linked(part):
            raise ValueError(f"Links and junctions are skipped: {path}")
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Not a regular file: {path}")
    return FileIdentity(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def matches(path: str | Path, identity: FileIdentity) -> bool:
    try:
        return regular_identity(path) == identity
    except (OSError, ValueError):
        return False


def directory_case_sensitive(path: Path) -> bool:
    if os.name == "nt":
        return False  # Conservative on Windows directories with opt-in case sensitivity.
    if sys.platform.startswith("linux"):
        try:
            import array
            import fcntl
            flags = array.array("L", [0])
            with open_directory(path) as handle:
                fcntl.ioctl(handle, 0x80086601, flags, True)  # FS_IOC_GETFLAGS, 64-bit Linux
            return not bool(flags[0] & 0x40000000)  # FS_CASEFOLD_FL
        except OSError:
            pass
    return True


class open_directory:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        return self.fd

    def __exit__(self, *_):
        os.close(self.fd)


def path_key(path: str | Path, sensitivity: dict[str, bool] | None = None) -> str:
    path = Path(os.path.abspath(path))
    parent = str(path.parent)
    if sensitivity is None:
        sensitive = directory_case_sensitive(path.parent)
    else:
        if parent not in sensitivity:
            sensitivity[parent] = directory_case_sensitive(path.parent)
        sensitive = sensitivity[parent]
    value = str(path)
    return value if sensitive else value.casefold()


def scan_paths(paths: list[str], recursive: bool, cancelled=lambda: False) -> tuple[list[FileEntry], list[str]]:
    entries, errors, seen = [], [], set()
    sensitivity: dict[str, bool] = {}
    stack = list(reversed(paths))
    while stack and not cancelled():
        path = Path(os.path.abspath(stack.pop()))
        try:
            if hidden_path(path):
                errors.append(f"Skipped hidden item: {path}")
                continue
            if linked(path):
                errors.append(f"Skipped link: {path}")
                continue
            if path.is_dir():
                for child in sorted(path.iterdir(), key=lambda item: item.name.casefold(), reverse=True):
                    if child.is_dir() and not recursive:
                        continue
                    stack.append(str(child))
                continue
            key = path_key(path, sensitivity)
            if key not in seen:
                entries.append(FileEntry(str(path), regular_identity(path)))
                seen.add(key)
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    return entries, errors


def windows_name_limit(directory: Path) -> int:
    """Ask the actual volume (including mounted volumes) for its component limit."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    volume = ctypes.create_unicode_buffer(32768)
    get_path = kernel.GetVolumePathNameW
    get_path.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_path.restype = wintypes.BOOL
    if not get_path(str(directory), volume, len(volume)):
        return 255
    get_info = kernel.GetVolumeInformationW
    get_info.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                        ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    limit = wintypes.DWORD()
    if get_info(volume.value, None, 0, None, ctypes.byref(limit), None, None, 0) and limit.value:
        return limit.value
    return 255


def name_error(path: Path, limits: dict[str, int] | None = None) -> str:
    name = path.name
    error = filename_error(name)
    if error:
        return error
    if os.name == "nt":
        limits = {} if limits is None else limits
        parent = str(path.parent)
        if parent not in limits:
            limits[parent] = windows_name_limit(path.parent)
        try:
            name_length = len(name.encode("utf-16-le")) // 2
            path_length = len(native_path(path).encode("utf-16-le")) // 2
        except UnicodeEncodeError:
            return "Filename contains invalid Unicode"
        if name_length > limits[parent] or path_length > 32700:
            return "Filename or path is too long"
    else:
        try:
            limit = os.pathconf(path.parent, "PC_NAME_MAX")
        except (OSError, ValueError):
            limit = 255
        if limit < 0:
            limit = 255
        if len(os.fsencode(name)) > limit:
            return f"Filename exceeds {limit} bytes"
        try:
            path_limit = os.pathconf(path.parent, "PC_PATH_MAX")
        except (OSError, ValueError):
            path_limit = 4096
        if path_limit > 0 and len(os.fsencode(os.path.abspath(path))) >= path_limit:
            return f"Path exceeds {path_limit - 1} bytes"
    return ""


def native_path(path: str | Path) -> str:
    value = os.path.abspath(path)
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        return "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
    return value


def rename_no_replace(source: str, target: str) -> None:
    """Atomic no-clobber move. Never fall back to POSIX os.rename (which overwrites)."""
    if os.name == "nt":
        os.rename(native_path(source), native_path(target))
    elif sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise OSError("This Linux runtime lacks safe renameat2; no files were overwritten")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1):  # RENAME_NOREPLACE
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), target)
    else:
        raise OSError("Safe renaming is supported on Windows and Linux only")
