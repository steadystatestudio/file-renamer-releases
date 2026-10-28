"""Build native portable distributions. Run on the operating system being packaged."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from build_manifest import write_bundle_info, write_manifest
from fetch_appimagetool import SHA256, SIZE, verify_file
from fetch_appimagetool import main as fetch_appimage_inputs

ROOT = Path(__file__).resolve().parents[1]


def icon_png(target: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    renderer = QSvgRenderer(str(ROOT / "src/file_renamer/assets/icon.svg"))
    image = QImage(256, 256, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    if not image.save(str(target)):
        raise RuntimeError("Could not create application icon")
    del app


def main() -> int:
    if sys.platform not in {"win32", "linux"}:
        raise SystemExit("Build on Windows or Linux.")
    if sys.platform == "linux" and platform.machine().lower() not in {"x86_64", "amd64"}:
        raise SystemExit("The Linux AppImage target requires an x86-64 build host.")
    os.chdir(ROOT)
    subprocess.run([sys.executable, str(ROOT / "scripts/build_rule_tools.py")], check=True)
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    # Keep build caches inside this project, including in sandboxed environments.
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(build / "pyinstaller-cache")
    icon_png(build / "icon.png")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--distpath", str(ROOT / "dist"), "--workpath", str(build / "pyinstaller"),
               str(ROOT / "packaging/File-Renamer.spec")]
    # All replaceable generated targets are confined to the project build/dist directories.
    for target in (build, ROOT / "dist"):
        if not target.resolve().is_relative_to(ROOT):
            raise RuntimeError("Build output escaped the project")
    subprocess.run(command, check=True)
    bundle = ROOT / "dist/File-Renamer"
    shutil.copy2(ROOT / "README.md", bundle / "README.md")
    shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE.txt")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", bundle / "THIRD_PARTY_NOTICES.md")
    if (ROOT / "docs").exists():
        shutil.copytree(ROOT / "docs", bundle / "docs", dirs_exist_ok=True)
    # Include the installed dependency license texts alongside the dynamic libraries.
    import importlib.metadata
    licenses = bundle / "licenses"
    licenses.mkdir(exist_ok=True)
    shutil.copytree(ROOT / "packaging/licenses", licenses, dirs_exist_ok=True)
    from fetch_release_sources import source_index
    from PySide6.QtCore import qVersion
    index = source_index()
    if qVersion() != index["qt_version"]:
        raise RuntimeError("Qt runtime differs from the retained source pins")
    (bundle / "SOURCE-INDEX.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(ROOT / "packaging/LIBRARY-REPLACEMENT.txt", bundle / "LIBRARY-REPLACEMENT.txt")
    if sys.platform == "linux":
        shutil.copy2(ROOT / "packaging/linux/APPIMAGE_RUNTIME_LICENSE.txt", licenses / "APPIMAGE_RUNTIME_LICENSE.txt")
        shutil.copy2(ROOT / "build/LINUX-SYSTEM-DEPENDENCIES.json", bundle / "LINUX-SYSTEM-DEPENDENCIES.json")
        shutil.copy2(ROOT / "packaging/linux/README-LINUX.txt", bundle / "README-LINUX.txt")
    python_licenses = (Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_path("stdlib")) / "LICENSE.txt")
    for python_license in python_licenses:
        if python_license.exists():
            shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
            break
    else:
        raise RuntimeError("Python license text was not found in this build's interpreter distribution")
    versions = {name: importlib.metadata.version(name) for name in ("PySide6", "shiboken6", "PyInstaller", "tomli-w")}
    (bundle / "BUILD-INFO.txt").write_text(
        f"Python: {sys.version}\n" + "\n".join(f"{name}: {version}" for name, version in versions.items()),
        encoding="utf-8")
    for name in ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "PyInstaller", "tomli-w"):
        distribution = importlib.metadata.distribution(name)
        for entry in distribution.files or []:
            relative = Path(str(entry))
            if relative.suffix in {".py", ".pyc", ".pyo"} or "__pycache__" in relative.parts:
                continue
            if any(word in str(entry).upper() for word in ("LICENSE", "COPYING", "NOTICE", "COPYRIGHT")):
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    safe_parts = [part for part in relative.parts if part not in ("..", ".", relative.anchor)]
                    target = licenses / name / Path(*safe_parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    inventory = {path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(licenses.rglob("*")) if path.is_file() and not path.is_symlink()}
    (bundle / "LICENSE-INDEX.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    native = {path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted((bundle / "_internal").rglob("*"))
              if path.is_file() and (path.suffix.lower() in {".dll", ".pyd"} or ".so" in path.name)}
    (bundle / "NATIVE-LIBRARIES.json").write_text(json.dumps(native, indent=2) + "\n", encoding="utf-8")
    if sys.platform == "win32":
        write_bundle_info(bundle)
        archive = shutil.make_archive(str(ROOT / "dist/File-Renamer-windows"), "zip", ROOT / "dist", "File-Renamer")
        write_manifest([Path(archive)])
        print(f"Built {archive}")
        return 0
    appdir = build / "File-Renamer.AppDir"
    write_bundle_info(bundle)
    tarball = shutil.make_archive(str(ROOT / "dist/File-Renamer-linux-x86_64"), "gztar", ROOT / "dist", "File-Renamer")
    if appdir.exists():
        if not appdir.resolve().is_relative_to(build.resolve()):
            raise RuntimeError("Unsafe AppDir path")
        shutil.rmtree(appdir)
    shutil.copytree(bundle, appdir / "usr/lib/file-renamer")
    shutil.copy2(build / "icon.png", appdir / "file-renamer.png")
    (appdir / "file-renamer.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=File Renamer\nExec=File-Renamer\n"
        "Icon=file-renamer\nCategories=Utility;FileTools;\nTerminal=false\n", encoding="utf-8")
    (appdir / "AppRun").write_text(
        '#!/bin/sh\nHERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
        'exec "$HERE/usr/lib/file-renamer/File-Renamer" "$@"\n', encoding="utf-8")
    (appdir / "AppRun").chmod(0o755)
    fetch_appimage_inputs()
    tool = Path(os.environ.get("APPIMAGETOOL") or build / "tools/appimagetool")
    if not verify_file(tool, SHA256, SIZE):
        raise SystemExit("APPIMAGETOOL does not match the reviewed packaging tool checksum.")
    environment = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
    output = ROOT / "dist/File-Renamer-x86_64.AppImage"
    subprocess.run([str(tool), "--runtime-file", str(build / "tools/runtime-x86_64"),
                    str(appdir), str(output)], check=True, env=environment)
    write_manifest([Path(tarball), output])
    print(f"Built {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
