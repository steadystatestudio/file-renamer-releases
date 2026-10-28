"""Read-only QA of the exact retained File Renamer 2.0.2 candidate.

This script does not build, replace, upload, publish, or edit any release asset.
Run from the audit-only workflow. Application source stays pinned to SOURCE.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

REPOSITORY = 'steadystatestudio/file-renamer-releases'
SOURCE = '85f7139b2620bf5059968349b4580455a23966b1'
TREE = '02f48cb3517e67813b203380725075c77e1cc273'
TAG = 'v2.0.2'
ROOT = Path('retained-candidate')


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(names):
    command = ['gh', 'release', 'download', TAG, '--repo', REPOSITORY, '--dir', str(ROOT)]
    for name in names:
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('Unsafe retained asset name')
        command += ['--pattern', name]
    subprocess.run(command, check=True)


def safe_member(name):
    parts = Path(name).parts
    if not parts or parts[0] != 'File-Renamer' or '..' in parts or '\\' in name or Path(name).is_absolute():
        raise ValueError(f'Unexpected package path: {name}')


def unpack(path, target):
    target.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.zip':
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                safe_member(item.filename)
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Unexpected Windows archive symlink')
            archive.extractall(target)
    else:
        expected = (target / 'File-Renamer').resolve()
        with tarfile.open(path) as archive:
            for item in archive.getmembers():
                safe_member(item.name)
                if item.issym() or item.islnk():
                    base = target / Path(item.name).parent if item.issym() else target
                    if not (base / item.linkname).resolve().is_relative_to(expected):
                        raise ValueError('Package symlink escapes the bundle')
            archive.extractall(target, filter='data')
    return target / 'File-Renamer'


def audit_bundle(bundle, platform):
    allowed = {'README.md', 'LICENSE.txt', 'THIRD_PARTY_NOTICES.md', 'docs', 'licenses', '_internal',
               'BUILD-INFO.txt', 'BUILD-INFO.json', 'SOURCE-INDEX.json', 'LIBRARY-REPLACEMENT.txt',
               'LICENSE-INDEX.json', 'NATIVE-LIBRARIES.json', 'File-Renamer.exe' if platform == 'Windows' else 'File-Renamer'}
    if platform == 'Linux':
        allowed |= {'README-LINUX.txt', 'LINUX-SYSTEM-DEPENDENCIES.json'}
    if {p.name for p in bundle.iterdir()} != allowed:
        raise ValueError(f'Unexpected or missing package root entries on {platform}')
    files = sorted(p for p in bundle.rglob('*') if p.is_file())
    forbidden = {'settings.ini', 'last-rename.json', 'last-rename.log', 'presets.json', '.env', 'credentials.json'}
    for path in files:
        if path.name.lower() in forbidden or any(part.lower() in {'.git', 'appdata', '__pycache__'}
                                                for part in path.relative_to(bundle).parts):
            raise ValueError('Runtime data, credentials or development cache found in package')
    info = json.loads((bundle / 'BUILD-INFO.json').read_text())
    if (info['source_commit'] != SOURCE or info['source_tree'] != TREE or info['source_dirty']
            or info['repository'] != REPOSITORY or info['platform'] != platform or info['version'] != '2.0.2'):
        raise ValueError('Retained package provenance differs from reviewed release source')
    indexes = {}
    for filename in ('LICENSE-INDEX.json', 'NATIVE-LIBRARIES.json'):
        index = json.loads((bundle / filename).read_text())
        if not index:
            raise ValueError('Empty package inventory')
        for name, sha in index.items():
            path = bundle / name
            if not path.resolve().is_relative_to(bundle.resolve()) or not path.is_file() or digest(path) != sha:
                raise ValueError(f'Inventory mismatch: {name}')
        indexes[filename] = len(index)
    libraries = json.loads((bundle / 'NATIVE-LIBRARIES.json').read_text())
    excluded = ('qt6pdf', 'qt6virtualkeyboard', 'qt6qml', 'qt6quick', 'qt6webengine', 'qt6network')
    for name in libraries:
        short = Path(name).name.lower().removeprefix('lib')
        if short.startswith(excluded) or short == 'opengl32sw.dll':
            raise ValueError(f'Unexpected optional Qt component: {name}')
    metadata_tools = bundle / '_internal/file_renamer/assets/tools'
    if not (metadata_tools / 'PascalScript-LICENSE.md').is_file():
        raise ValueError('Missing PascalScript license')
    tool_notices = [p.relative_to(bundle).as_posix() for p in metadata_tools.rglob('*') if p.is_file()
                   and any(word in p.name.lower() for word in ('license', 'copyright', 'readme', 'copying', 'artistic'))]
    if platform == 'Linux' and not (metadata_tools / 'Perl-copyright.txt').is_file():
        raise ValueError('Missing bundled Perl notices')
    source_index = json.loads((bundle / 'SOURCE-INDEX.json').read_text())
    if source_index['qt_version'] != '6.11.0':
        raise ValueError('Mismatched Qt source inventory')
    result = {'platform': platform, 'file_count': len(files), 'inventories_verified': indexes,
              'shared_libraries': sorted(libraries), 'native_tool_notices': tool_notices,
              'root_entries': sorted(allowed), 'runtime_settings_or_history': 'absent',
              'source_commit': SOURCE, 'source_tree': TREE}
    (ROOT / f'AUDIT-{platform}.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


def main():
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise ValueError('Wrong audit repository')
    matches = [item for item in api(f'repos/{REPOSITORY}/releases?per_page=100') if item['tag_name'] == TAG]
    if len(matches) != 1:
        raise ValueError('Exact retained draft release not found uniquely')
    release = matches[0]
    if (release.get('draft') is not True or release.get('prerelease') is not True
            or release.get('target_commitish') != SOURCE):
        raise ValueError('Audit requires the exact reviewed draft; no release is modified')
    assets = {item['name']: item for item in release['assets']}
    ROOT.mkdir(exist_ok=True)
    download(['RELEASE-READY.json'])
    ready = json.loads((ROOT / 'RELEASE-READY.json').read_text())
    if ready['source_commit'] != SOURCE or ready['source_tree'] != TREE:
        raise ValueError('Readiness evidence points elsewhere')
    records = {item['name']: item for item in ready['files']}
    if set(assets) != set(records) | {'RELEASE-READY.json'}:
        raise ValueError('Unreviewed or missing assets')
    for name, record in records.items():
        if assets[name]['digest'] != 'sha256:' + record['sha256'] or assets[name]['size'] != record['size']:
            raise ValueError('Release asset metadata differs from validated receipt')
    names = ['File-Renamer-windows.zip', 'File-Renamer-linux-x86_64.tar.gz', 'File-Renamer-x86_64.AppImage',
             'File-Renamer-source.zip', 'BUILD-INFO-Windows.json', 'BUILD-INFO-Linux.json']
    download(names)
    for name in names:
        if digest(ROOT / name) != records[name]['sha256']:
            raise ValueError(f'Retained-byte checksum mismatch: {name}')
    with zipfile.ZipFile(ROOT / 'File-Renamer-source.zip') as archive:
        if archive.comment.decode() != SOURCE:
            raise ValueError('Source snapshot does not identify the exact release commit')
        if any('.git' in Path(name).parts for name in archive.namelist()):
            raise ValueError('Private Git history was included')
    for platform, name in [('Windows', 'File-Renamer-windows.zip'), ('Linux', 'File-Renamer-linux-x86_64.tar.gz')]:
        bundle = unpack(ROOT / name, ROOT / platform)
        audit_bundle(bundle, platform)
    print('Exact retained bytes, provenance, license/native-library inventory and runtime-data exclusions passed.')


if __name__ == '__main__':
    main()
