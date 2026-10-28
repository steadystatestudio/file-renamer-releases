#!/usr/bin/env bash
# Run inside the dedicated WSL distribution; build on ext4, export only Linux deliverables.
set -euo pipefail
source_root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
build_root=/opt/file-renamer/work
uv=/opt/file-renamer/tools/uv-x86_64-unknown-linux-gnu/uv
if [[ ! -x "$uv" ]]; then
    echo "Run scripts/setup_linux_build.sh inside this distribution first." >&2
    exit 1
fi
mkdir -p "$build_root"
if [[ $(readlink -f "$build_root") != /opt/file-renamer/work ]]; then
    echo "Unexpected build directory; refusing to synchronize." >&2
    exit 1
fi
for directory in src tests scripts packaging docs .github native; do
    mkdir -p "$build_root/$directory"
    rsync -a --delete --exclude=__pycache__ --exclude='*.egg-info' --exclude=assets/tools \
        "$source_root/$directory/" "$build_root/$directory/"
done
for file in pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md .gitignore; do
    cp "$source_root/$file" "$build_root/$file"
done
cd "$build_root"
if [[ ! -x .venv/bin/python ]]; then
    "$uv" venv --python 3.12 --seed .venv
fi
"$uv" pip install --python .venv/bin/python -c packaging/build-constraints.txt -e '.[dev,packaging]'
export QT_QPA_PLATFORM=offscreen
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
mkdir -p artifacts
.venv/bin/python scripts/build_rule_tools.py
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m pytest -q --junitxml=artifacts/linux-tests.xml
.venv/bin/python scripts/render_preview.py artifacts/linux-screenshots
.venv/bin/python scripts/render_rules.py artifacts/linux-screenshots/rules
.venv/bin/python scripts/fetch_appimagetool.py
export APPIMAGETOOL="$build_root/build/tools/appimagetool"
.venv/bin/python scripts/build.py
.venv/bin/python scripts/smoke_bundle.py dist/File-Renamer/File-Renamer
APPIMAGE_EXTRACT_AND_RUN=1 .venv/bin/python scripts/smoke_bundle.py dist/File-Renamer-x86_64.AppImage
FILE_RENAMER_SMOKE_PLATFORM=xcb APPIMAGE_EXTRACT_AND_RUN=1 \
    xvfb-run -a -s '-screen 0 1920x1080x24' .venv/bin/python scripts/smoke_bundle.py dist/File-Renamer-x86_64.AppImage
(cd dist && sha256sum File-Renamer-x86_64.AppImage > File-Renamer-x86_64.AppImage.sha256)
mkdir -p "$source_root/dist" "$source_root/artifacts/linux"
cp dist/File-Renamer-x86_64.AppImage dist/File-Renamer-x86_64.AppImage.sha256 "$source_root/dist/"
cp artifacts/linux-tests.xml "$source_root/artifacts/linux/"
cp dist/File-Renamer/BUILD-INFO.txt "$source_root/artifacts/linux/"
rsync -a artifacts/linux-screenshots/ "$source_root/artifacts/linux/screenshots/"
echo "Linux AppImage built, tested, and exported to $source_root/dist."
