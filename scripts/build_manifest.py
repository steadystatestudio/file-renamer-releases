"""Record the exact source and dependency versions of a testing package."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_info() -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT.as_posix()}", "-C", str(ROOT), *args], text=True
        ).strip()

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return {
        "repository": "steadystatestudio/file-renamer-releases",
        "source_commit": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "source_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "version": project["version"],
        "platform": platform.system(),
        "architecture": platform.machine(),
        "python": sys.version,
        "dependencies": {
            dist.metadata["Name"]: dist.version
            for dist in sorted(importlib.metadata.distributions(), key=lambda item: item.metadata["Name"].lower())
        },
        "packages": [],
        "validation": {"source": "artifacts/tests.xml", "packaged": "scripts/smoke_bundle.py"},
        "release_status": "unsigned candidate; publication is a separate reviewed action",
    }


def write_bundle_info(bundle: Path) -> None:
    (bundle / "BUILD-INFO.json").write_text(json.dumps(build_info(), indent=2) + "\n", encoding="utf-8")


def write_manifest(packages: list[Path]) -> None:
    info = build_info()
    for package in packages:
        with package.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        info["packages"].append({
            "filename": package.name,
            "sha256": digest,
        })
    dist = ROOT / "dist"
    (dist / "BUILD-INFO.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    (dist / "SHA256SUMS").write_text(
        "".join(f"{item['sha256']}  {item['filename']}\n" for item in info["packages"]), encoding="utf-8"
    )

