#!/usr/bin/env bash
# Bootstrap only the dedicated File-Renamer-Build Ubuntu distribution.
set -euo pipefail
if [[ $(id -u) != 0 ]]; then
    echo "Run this setup as root inside the dedicated build distribution." >&2
    exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
    ca-certificates curl rsync binutils patchelf desktop-file-utils squashfs-tools libfuse2 \
    fp-compiler fp-units-fcl fp-units-base libc6-dev perl \
    libegl1 libopengl0 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1 fonts-dejavu-core \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
    libxcb-xinerama0 libxcb-xkb1 libxcb-shape0 libxkbcommon-x11-0 xvfb xauth

if [[ ${1:-} == --system-only ]]; then
    exit 0
fi

mkdir -p /opt/file-renamer/tools
cd /opt/file-renamer/tools
uv_version=0.12.13
uv_archive=uv-x86_64-unknown-linux-gnu.tar.gz
curl -fLsS --retry 3 "https://github.com/astral-sh/uv/releases/download/$uv_version/$uv_archive" -o "$uv_archive"
curl -fLsS --retry 3 "https://github.com/astral-sh/uv/releases/download/$uv_version/$uv_archive.sha256" -o "$uv_archive.sha256"
sha256sum -c "$uv_archive.sha256"
tar -xzf "$uv_archive"
./uv-x86_64-unknown-linux-gnu/uv python install 3.12
echo "Linux build prerequisites installed."
