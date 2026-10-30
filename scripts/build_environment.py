"""Keep unrelated Windows tools on the host PATH out of PyInstaller DLL scans."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def pyinstaller_environment() -> dict[str, str]:
    environment = dict(os.environ)
    if sys.platform == "win32":
        windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
        locations = [Path(sys.executable).parent, Path(sys.base_prefix),
                     Path(sys.base_prefix) / "DLLs", windows / "System32", windows]
        environment["PATH"] = os.pathsep.join(dict.fromkeys(str(path) for path in locations))
    return environment
