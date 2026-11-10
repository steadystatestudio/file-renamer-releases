from __future__ import annotations

import ctypes
import os
import re
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


# Filesystems whose inode numbers are permanent properties of a file. FAT,
# exFAT, network and FUSE mounts assign numbers when a file is loaded, so the
# same file can report a different inode (or device) later in one batch.
STABLE_ID_FILESYSTEMS = frozenset({
    "bcachefs", "btrfs", "ext2", "ext3", "ext4", "f2fs", "jfs", "nilfs2",
    "ntfs", "refs", "tmpfs", "xfs", "zfs",
})
_filesystem_types: dict[str, str] = {}


def _linux_filesystem_type(directory: str) -> str:
    best, found = -1, ""
    with open("/proc/self/mountinfo", encoding="utf-8", errors="surrogateescape") as handle:
        for line in handle:
            left, separator, right = line.partition(" - ")
            fields = left.split()
            if not separator or len(fields) < 5:
                continue
            # Spaces and similar bytes in a mount point are written as \040 octal escapes.
            mount = os.fsdecode(re.sub(
                rb"\\([0-7]{3})", lambda found: bytes([int(found.group(1), 8)]), os.fsencode(fields[4])))
            inside = directory == mount or directory.startswith(mount.rstrip("/") + "/")
            # A later line for the same mount point is the one mounted on top.
            if inside and len(mount) >= best:
                best, found = len(mount), right.split()[0]
    return found


def _windows_filesystem_type(directory: str) -> str:
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    volume = ctypes.create_unicode_buffer(32768)
    kernel.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumePathNameW.restype = wintypes.BOOL
    if not kernel.GetVolumePathNameW(directory, volume, len(volume)):
        return ""
    name = ctypes.create_unicode_buffer(64)
    kernel.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumeInformationW.restype = wintypes.BOOL
    if not kernel.GetVolumeInformationW(volume.value, None, 0, None, None, None, name, len(name)):
        return ""
    return name.value


def filesystem_type(directory: str | Path) -> str:
    """Lower-case filesystem name for a directory, or "" when it cannot be read."""
    directory = os.path.realpath(directory)
    if directory not in _filesystem_types:
        try:
            if os.name == "nt":
                found = _windows_filesystem_type(directory)
            elif sys.platform.startswith("linux"):
                found = _linux_filesystem_type(directory)
            else:
                found = ""
        except (OSError, ValueError):
            found = ""
        if len(_filesystem_types) > 256:
            _filesystem_types.clear()
        _filesystem_types[directory] = found.lower()
    return _filesystem_types[directory]


def stable_file_ids(directory: str | Path) -> bool:
    return filesystem_type(directory) in STABLE_ID_FILESYSTEMS


def matches(path: str | Path, identity: FileIdentity) -> bool:
    """Whether path still holds the recorded file.

    Device and inode are compared only where they are permanent. Elsewhere a
    regular, unlinked file with the recorded size and modification time at the
    recorded path is the same file; every move remains no-clobber regardless.
    """
    try:
        found = regular_identity(path)
    except (OSError, ValueError):
        return False
    if found == identity:
        return True
    if (found.size, found.modified_ns) != (identity.size, identity.modified_ns):
        return False
    return not stable_file_ids(Path(os.path.abspath(path)).parent)


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
    return _probe_case_sensitive(path)


def _probe_case_sensitive(path: Path) -> bool:
    """Ask the directory itself (FAT, exFAT, NTFS and network mounts have no flag).

    An existing name answers under its swapped-case spelling only on a
    case-insensitive directory, unless that spelling is a real sibling.
    """
    try:
        with os.scandir(path) as entries:
            for count, entry in enumerate(entries):
                if count >= 64:
                    break
                swapped = entry.name.swapcase()
                if swapped == entry.name:
                    continue
                try:
                    os.lstat(os.path.join(path, swapped))
                except FileNotFoundError:
                    return True
                except OSError:
                    continue
                return swapped in os.listdir(path)
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
                if path.name.startswith(".file-renamer-") and path.suffix == ".tmp":
                    errors.append(f"Left by an interrupted rename; use Recover to restore its name: {path}")
                else:
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
