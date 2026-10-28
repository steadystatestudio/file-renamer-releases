"""Compile the naming helper and stage pinned, offline metadata dependencies."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "build/tools"
DEST = ROOT / "src/file_renamer/assets/tools"
RELEASE = "13.59"
DOWNLOADS = {
    "fpc-win64.tar": (
        "https://downloads.freepascal.org/fpc/dist/3.2.2/x86_64-win64/fpc-3.2.2.x86_64-win64.tar",
        "10d776cf6e86dccab482b81285da58a9cc8e0aa9c0558b78d3bf08d3981b4924",
    ),
    "exiftool-win.zip": (
        f"https://downloads.sourceforge.net/project/exiftool/exiftool-{RELEASE}_64.zip",
        "44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec",
    ),
    "exiftool.tar.gz": (
        f"https://downloads.sourceforge.net/project/exiftool/Image-ExifTool-{RELEASE}.tar.gz",
        "668ea3acececb7235fbd0f4900e72d5f12c9b07e5c778fd36cb1e9b5828fd65a",
    ),
}


def fetch(filename):
    url, digest = DOWNLOADS[filename]
    target = TOOLS / filename
    if not target.exists():
        with urllib.request.urlopen(url, timeout=120) as response:
            target.write_bytes(response.read())
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f"Checksum mismatch for {filename}; review the dependency release")
    return target


def extract_tar(archive, destination):
    with tarfile.open(archive) as tar:
        for entry in tar.getmembers():
            if (
                entry.issym()
                or entry.islnk()
                or not (destination / entry.name).resolve().is_relative_to(destination.resolve())
            ):
                raise RuntimeError("Unsafe archive path")
        tar.extractall(destination, filter="data")


def windows_compiler():
    base = TOOLS / "fpc-win64/compiler"
    compiler = base / "bin/x86_64-win64/ppcx64.exe"
    if not compiler.is_file():
        staging = TOOLS / "fpc-download"
        extract_tar(fetch("fpc-win64.tar"), staging)
        archive = next(staging.rglob("binary.x86_64-win64.tar"))
        packages = staging / "packages"
        extract_tar(archive, packages)
        required = (
            "x86_64-win64-base",
            "units-rtl-objpas",
            "units-rtl-unicode",
            "units-winunits-base",
            "units-fcl-json",
            "units-fcl-base",
            "units-fcl-registry",
            "units-regexpr",
        )
        for name in required:
            extract_tar(next(packages.rglob(name + ".*.tar.gz")), base)
    return compiler, base


def compile_runtime():
    declarations = (ROOT / "native/rule_runtime.pas").read_text() + (ROOT / "native/naming_registry.inc").read_text()
    names = re.findall(r"RegisterFunction\('(.*?)'", declarations)
    names += re.findall(
        r"(?im)^((?:function|procedure)\s+\w+[^;]*;)", (ROOT / "src/file_renamer/assets/pascal-support.pas").read_text()
    )
    catalog = sorted({re.search(r"(?:function|procedure)\s+(\w+)", name, re.I)[1] for name in names})
    catalog = [name for name in catalog if not name.startswith("Naming")]
    (ROOT / "src/file_renamer/assets/pascal-functions.json").write_text(json.dumps(catalog, indent=2) + "\n")
    compiler = os.environ.get("FPC") or shutil.which("fpc")
    paths = []
    if not compiler and sys.platform == "win32":
        executable, base = windows_compiler()
        compiler = str(executable)
        paths = ["-n", "-Fu" + str(base / "units/x86_64-win64/rtl")]
        paths += ["-Fu" + str(p) for p in (base / "lib/fpc/3.2.2/units/x86_64-win64").glob("*")]
    if not compiler or not (shutil.which(compiler) or Path(compiler).is_file()):
        raise RuntimeError("Install Free Pascal 3.2.2 or set FPC to the compiler executable")
    output = ROOT / "build/native" / sys.platform
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            compiler,
            *paths,
            "-Fu" + str(ROOT / "native/vendor/pascalscript"),
            "-FU" + str(output),
            "-FE" + str(output),
            str(ROOT / "native/rule_runtime.pas"),
        ],
        check=True,
    )
    filename = "rule_runtime.exe" if sys.platform == "win32" else "rule_runtime"
    shutil.copy2(output / filename, DEST / filename)
    shutil.copy2(ROOT / "native/vendor/pascalscript/LICENSE.md", DEST / "PascalScript-LICENSE.md")


def stage_metadata():
    if sys.platform == "win32":
        archive = fetch("exiftool-win.zip")
        staging = TOOLS / "exiftool-windows"
        with zipfile.ZipFile(archive) as zip_file:
            for entry in zip_file.infolist():
                if not (staging / entry.filename).resolve().is_relative_to(staging.resolve()):
                    raise RuntimeError("Unsafe archive path")
            zip_file.extractall(staging)
        executable = next(staging.rglob("exiftool(-k).exe"))
        shutil.copy2(executable, DEST / "exiftool.exe")
        shutil.copytree(executable.parent / "exiftool_files", DEST / "exiftool_files", dirs_exist_ok=True)
        return
    archive = fetch("exiftool.tar.gz")
    staging = TOOLS / "exiftool-linux"
    extract_tar(archive, staging)
    source = staging / f"Image-ExifTool-{RELEASE}"
    shutil.copy2(source / "exiftool", DEST / "exiftool.pl")
    shutil.copytree(source / "lib", DEST / "lib", dirs_exist_ok=True)
    perl = shutil.which("perl")
    if not perl:
        raise RuntimeError("Perl is required to build the bundled metadata reader")
    config = subprocess.check_output([perl, "-MConfig", "-e", 'print "$Config{privlib}\n$Config{archlib}"'], text=True)
    pure, arch = config.strip().splitlines()
    runtime = DEST / "perl"
    runtime.mkdir(exist_ok=True)
    shutil.copy2(perl, runtime / "perl")
    shutil.copytree(pure, runtime / "lib", dirs_exist_ok=True)
    shutil.copytree(arch, runtime / "archlib", dirs_exist_ok=True)
    for line in subprocess.check_output(["ldd", perl], text=True).splitlines():
        if "libcrypt.so" in line and "=>" in line:
            library = Path(line.split("=>", 1)[1].strip().split()[0])
            shutil.copy2(library, runtime / "libcrypt.so.1")
    (DEST / "exiftool").write_text(
        '#!/bin/sh\nHERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
        'export LD_LIBRARY_PATH="$HERE/perl:${LD_LIBRARY_PATH:-}"\n'
        'exec "$HERE/perl/perl" -I "$HERE/perl/lib" -I "$HERE/perl/archlib" '
        '-I "$HERE/lib" "$HERE/exiftool.pl" "$@"\n',
        encoding="utf-8",
    )
    (DEST / "exiftool").chmod(0o755)
    shutil.copy2(source / "README", DEST / "ExifTool-README.txt")
    for name, path in (
        ("Perl-copyright.txt", "/usr/share/doc/perl/copyright"),
        ("libcrypt-copyright.txt", "/usr/share/doc/libcrypt1/copyright"),
    ):
        if Path(path).exists():
            shutil.copy2(path, DEST / name)


def main():
    TOOLS.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    compile_runtime()
    stage_metadata()
    print("Native rule tools are ready")


if __name__ == "__main__":
    main()
