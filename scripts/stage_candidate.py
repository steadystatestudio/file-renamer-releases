"""Retain exact-commit packages in an unpublished draft. This tool never publishes.

Adapted from Steady State Studio Contact Sheet Maker's MIT release workflow.
Only synthetic screenshots, passing test reports and clean tracked source are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "steadystatestudio/file-renamer-releases"
PLATFORMS = ("Windows", "Linux", "Sources")


def api(path, payload=None):
    command = ["gh", "api", path]
    if payload is not None:
        command += ["--method", "POST", "--input", "-"]
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def identity():
    commit = os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or git("rev-parse", "HEAD") != commit:
        raise ValueError("Candidate must be the exact triggering commit")
    if commit != os.environ.get("REVIEWED_COMMIT"):
        raise ValueError("The manually reviewed commit must match the workflow commit")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if os.environ.get("RELEASE_TAG") != f"v{version}":
        raise ValueError("Release tag must match the package version")
    return commit, git("rev-parse", "HEAD^{tree}"), f"v{version}"


def validate_draft(release, commit, tag):
    if (release.get("draft") is not True or release.get("prerelease") is not True
            or release.get("tag_name") != tag or release.get("target_commitish") != commit):
        raise ValueError("Only this exact-commit draft prerelease may be modified")


def current_release():
    commit, _, tag = identity()
    release = api(f"repos/{REPOSITORY}/releases/{int(os.environ['RELEASE_ID'])}")
    validate_draft(release, commit, tag)
    matches = [item for item in release_inventory() if item.get("tag_name") == tag]
    if len(matches) != 1 or matches[0].get("id") != release.get("id"):
        raise ValueError("Release tag does not uniquely identify the selected draft")
    return release


def record(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Unsafe or missing asset: {path.name}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"name": path.name, "size": path.stat().st_size, "sha256": digest}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def invalidate_ready(release):
    for asset in release.get("assets", []):
        if asset.get("name") == "RELEASE-READY.json":
            try:
                subprocess.run(["gh", "api", "--method", "DELETE",
                                f"repos/{REPOSITORY}/releases/assets/{int(asset['id'])}"],
                               capture_output=True, text=True, check=True)
            except subprocess.CalledProcessError as exc:
                # A parallel platform job may already have invalidated this same receipt.
                if "HTTP 404" not in (exc.stderr or ""):
                    raise


def upload(paths):
    release = current_release()
    for path in paths:
        record(path)  # Reject missing files and symlinks before invalidating readiness.
    # Rebuilt archives/QA and run IDs need not be byte-identical. Restaging is permitted
    # only in the unique, unpublished draft for this exact commit. Any previous ready
    # receipt is removed first; finalize verifies every replacement before recreating it.
    invalidate_ready(release)
    subprocess.run(["gh", "release", "upload", release['tag_name'], "--repo", REPOSITORY,
                    "--clobber", *(str(path) for path in paths)], check=True)


def release_inventory():
    result = []
    for page in range(1, 101):
        batch = api(f"repos/{REPOSITORY}/releases?per_page=100&page={page}")
        if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
            raise ValueError("Invalid release inventory")
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise ValueError("Release inventory pagination exceeded its safety bound")


def verify_destination(commit, tag):
    if api(f"repos/{REPOSITORY}").get("full_name") != REPOSITORY:
        raise ValueError("Unexpected release repository")
    if api(f"repos/{REPOSITORY}/commits/{commit}").get("sha") != commit:
        raise ValueError("Reviewed commit is missing from the release repository")
    try:
        obj = api(f"repos/{REPOSITORY}/git/ref/tags/{tag}")["object"]
    except subprocess.CalledProcessError as exc:
        if "HTTP 404" in (exc.stderr or ""):
            return
        raise
    for _ in range(10):
        if obj.get("type") == "commit":
            if obj.get("sha") != commit:
                raise ValueError("Existing release tag points to another commit")
            return
        if obj.get("type") != "tag" or not re.fullmatch(r"[0-9a-f]{40}", obj.get("sha", "")):
            break
        obj = api(f"repos/{REPOSITORY}/git/tags/{obj['sha']}")["object"]
    raise ValueError("Release tag does not resolve to the reviewed commit")


def check_smoke_report(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("success") is not True or data.get("rename") != "passed"
            or data.get("undo") != "passed" or data.get("originals_unchanged") is not True
            or not data.get("hashes_before") or data["hashes_before"] != data.get("hashes_after")):
        raise ValueError("Packaged rename and Undo verification is missing or failed")
    return data


def init():
    commit, tree, tag = identity()
    verify_destination(commit, tag)
    releases = release_inventory()
    matching = [release for release in releases if release['tag_name'] == tag]
    if len(matching) > 1:
        raise ValueError("Ambiguous release inventory")
    if matching:
        release = matching[0]
        validate_draft(release, commit, tag)
        invalidate_ready(release)
    else:
        release = api(f"repos/{REPOSITORY}/releases", {
            "tag_name": tag, "target_commitish": commit, "draft": True, "prerelease": True,
            "name": f"File Renamer {tag[1:]}",
            "body": "Draft only. Tests, native package smoke, exact source and license evidence "
                    "must pass before publication review. No workflow publishes this release. "
                    "This repository contains a clean audited source snapshot; publication is a separate review.",
        })
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as stream:
        stream.write(f"release_id={release['id']}\ncommit={commit}\ntree={tree}\n")


def check_test_report(path):
    suites = ET.parse(path).getroot()
    counts = {key: sum(int(suite.get(key, '0')) for suite in suites.iter('testsuite'))
              for key in ('tests', 'failures', 'errors', 'skipped')}
    if counts['tests'] == 0 or counts['failures'] or counts['errors']:
        raise ValueError("Only passing full-suite reports can be staged")
    return counts


def stage(platform):
    commit, tree, tag = identity()
    output = ROOT / 'dist/release-stage'
    output.mkdir(parents=True, exist_ok=True)
    tests = None
    if platform in {'Windows', 'Linux'}:
        info = json.loads((ROOT / 'dist/BUILD-INFO.json').read_text())
        if (info['source_commit'] != commit or info['source_tree'] != tree or info['source_dirty']
                or info['platform'] != platform or info['version'] != tag[1:]):
            raise ValueError('Package provenance does not match exact clean candidate source')
        from fetch_release_sources import source_index
        expected_qt = source_index()['qt_version']
        for name in ('PySide6', 'PySide6_Addons', 'PySide6_Essentials', 'shiboken6'):
            if info['dependencies'].get(name) != expected_qt:
                raise ValueError('Qt sources do not match package libraries')
        names = ['File-Renamer-windows.zip'] if platform == 'Windows' else [
            'File-Renamer-linux-x86_64.tar.gz', 'File-Renamer-x86_64.AppImage']
        files = [ROOT / 'dist' / name for name in names]
        files.append(write_json(output / f'BUILD-INFO-{platform}.json', info))
        tests = check_test_report(ROOT / 'artifacts/tests.xml')
        smoke_dirs = ['smoke-windows'] if platform == 'Windows' else ['smoke-bundle', 'smoke-appimage', 'smoke-x11']
        for folder in smoke_dirs:
            check_smoke_report(ROOT / 'artifacts' / folder / 'result.json')
        qa = output / f'QA-{platform}.zip'
        with zipfile.ZipFile(qa, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in [ROOT / 'artifacts/tests.xml', *sorted((ROOT / 'artifacts/screenshots').glob('*.png')),
                         *sorted((ROOT / 'artifacts').glob('smoke-*/ui*.png')),
                         *sorted((ROOT / 'artifacts').glob('smoke-*/result.json'))]:
                if path.is_file() and not path.is_symlink():
                    archive.write(path, path.relative_to(ROOT / 'artifacts').as_posix())
        files.append(qa)
    else:
        from fetch_release_sources import source_index
        index = source_index()
        files = [ROOT / 'dist/release-sources' / item['name'] for item in index['archives']]
        for item, path in zip(index['archives'], files):
            if record(path) != {key: item[key] for key in ('name', 'size', 'sha256')}:
                raise ValueError('Source archive differs from pinned upstream bytes')
        files.append(ROOT / 'dist/release-sources/SOURCE-INDEX.json')
        snapshot = output / 'File-Renamer-source.zip'
        subprocess.run(['git', 'archive', '--format=zip', '--prefix=File-Renamer-source/',
                        '--output', str(snapshot), commit], cwd=ROOT, check=True)
        files.append(snapshot)
    records = [record(path) for path in files]
    checksums = output / f'SHA256SUMS-{platform}.txt'
    checksums.write_text(''.join(f"{item['sha256']}  {item['name']}\n" for item in records), encoding='ascii')
    files.append(checksums)
    receipt = write_json(output / f'RELEASE-{platform}.json', {
        'source_commit': commit, 'source_tree': tree, 'platform': platform, 'tests': tests,
        'run_id': os.environ['GITHUB_RUN_ID'], 'files': [record(path) for path in files],
        'native_smoke': 'passed' if platform != 'Sources' else None,
    })
    upload(files)
    upload([receipt])


def finalize():
    commit, tree, tag = identity()
    release = current_release()
    verify_destination(commit, tag)
    directory = ROOT / 'dist/final'
    directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(['gh', 'release', 'download', tag, '--repo', REPOSITORY, '--dir', str(directory),
                    '--pattern', 'RELEASE-*.json'], check=True)
    assets = {item['name']: item for item in release['assets']}
    records = []
    for platform in PLATFORMS:
        path = directory / f'RELEASE-{platform}.json'
        receipt = json.loads(path.read_text())
        if (receipt.get('source_commit') != commit or receipt.get('source_tree') != tree
                or receipt.get('platform') != platform or receipt.get('run_id') != os.environ['GITHUB_RUN_ID']):
            raise ValueError('Receipt belongs to another source, run or platform')
        for item in [*receipt['files'], record(path)]:
            asset = assets.get(item['name'], {})
            if (asset.get('state') != 'uploaded' or asset.get('size') != item['size']
                    or asset.get('digest') != 'sha256:' + item['sha256']):
                raise ValueError(f"Retained asset failed verification: {item['name']}")
            records.append(item)
    names = [item['name'] for item in records]
    if len(names) != len(set(names)) or set(assets) - {'RELEASE-READY.json'} != set(names):
        raise ValueError('Missing, duplicate or unreviewed assets in the candidate')
    ready = write_json(directory / 'RELEASE-READY.json', {
        'status': 'automated-checks-passed-awaiting-publication-review', 'draft': True,
        'source_commit': commit, 'source_tree': tree, 'tag': tag,
        'run_id': os.environ['GITHUB_RUN_ID'], 'files': records,
        'remaining_review': ['package privacy and native-library inventory', 'clean public snapshot',
                             'public URLs and download checksums', 'interactive Windows/hardware limits'],
    })
    upload([ready])
    print('All automated release gates passed. Candidate remains DRAFT; no publication occurred.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'stage', 'finalize'])
    parser.add_argument('--platform', choices=PLATFORMS)
    args = parser.parse_args()
    if (os.environ.get('GITHUB_REPOSITORY') != REPOSITORY
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
        raise ValueError('Staging requires an explicit manual dispatch from the Studio main branch')
    if args.command == 'stage':
        if not args.platform:
            parser.error('stage requires --platform')
        stage(args.platform)
    else:
        {'init': init, 'finalize': finalize}[args.command]()


if __name__ == '__main__':
    main()
