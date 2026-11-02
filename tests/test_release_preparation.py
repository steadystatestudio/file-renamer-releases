import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_source_pins_match_locked_runtime():
    index = module('fetch_release_sources').source_index()
    assert index['qt_version'] == '6.11.0'
    assert len(index['archives']) == 5


def test_candidate_rejects_published_or_wrong_commit_release():
    stage = module('stage_candidate')
    release = dict(draft=True, prerelease=True, tag_name='candidate-a', target_commitish='a' * 40)
    stage.validate_draft(release, 'a' * 40, 'candidate-a')
    for mutation in (dict(draft=False), dict(prerelease=False), dict(tag_name='other'),
                     dict(target_commitish='b' * 40)):
        with pytest.raises(ValueError):
            stage.validate_draft(release | mutation, 'a' * 40, 'candidate-a')


@pytest.mark.parametrize('private', [True, False])
def test_build_repository_requires_private_visibility(monkeypatch, private):
    stage = module('stage_candidate')
    monkeypatch.setattr(stage, 'REPOSITORY', stage.PRIVATE_BUILD_REPOSITORY)
    commit = 'a' * 40

    def read_only(path, payload=None):
        assert payload is None
        if path == f'repos/{stage.REPOSITORY}':
            return dict(full_name=stage.REPOSITORY, private=private)
        if '/commits/' in path:
            return dict(sha=commit)
        return dict(object=dict(type='commit', sha=commit))

    monkeypatch.setattr(stage, 'api', read_only)
    if private:
        stage.verify_destination(commit, 'v2.0.5')
    else:
        with pytest.raises(ValueError, match='must remain private'):
            stage.verify_destination(commit, 'v2.0.5')


def test_unlisted_candidate_repository_is_rejected_before_network(monkeypatch):
    stage = module('stage_candidate')
    monkeypatch.setattr(stage, 'REPOSITORY', 'steadystatestudio/unlisted')
    monkeypatch.setattr(stage, 'api', lambda *_: pytest.fail('Unexpected network call'))
    with pytest.raises(ValueError, match='Unexpected release repository'):
        stage.verify_destination('a' * 40, 'v2.0.5')


def test_reviewed_commit_and_version_must_match(monkeypatch):
    stage = module('stage_candidate')
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    monkeypatch.setenv('REVIEWED_COMMIT', 'b' * 40)
    monkeypatch.setenv('RELEASE_TAG', 'v2.0.3')
    monkeypatch.setattr(stage, 'git', lambda *args: 'a' * 40)
    with pytest.raises(ValueError, match='reviewed commit'):
        stage.identity()
    monkeypatch.setenv('REVIEWED_COMMIT', 'a' * 40)
    monkeypatch.setenv('RELEASE_TAG', 'v2.0.2')
    with pytest.raises(ValueError, match='package version'):
        stage.identity()


def test_published_release_on_later_page_blocks_staging(monkeypatch):
    stage = module('stage_candidate')
    monkeypatch.setattr(stage, 'identity', lambda: ('a' * 40, 'b' * 40, 'v2.0.3'))
    monkeypatch.setattr(stage, 'verify_destination', lambda *_: None)
    pages = iter([[{'tag_name': f'old-{i}'} for i in range(100)],
                  [{'tag_name': 'v2.0.3', 'draft': False, 'prerelease': False}]])
    def read_only(path, payload=None):
        assert payload is None, 'No mutation is allowed after a published version is found'
        return next(pages)
    monkeypatch.setattr(stage, 'api', read_only)
    with pytest.raises(ValueError, match='draft prerelease'):
        stage.init()


def test_smoke_receipt_requires_unchanged_hashes(tmp_path):
    stage = module('stage_candidate')
    receipt = tmp_path / 'result.json'
    data = dict(success=True, rename='passed', undo='passed', originals_unchanged=True,
                hashes_before={'file': 'a'}, hashes_after={'file': 'b'},
                rule_creation='passed', rule_editing='passed', created_rule_kinds=['insert', 'replace'],
                tiff_metadata='passed', tiff_original_unchanged=True)
    receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='verification'):
        stage.check_smoke_report(receipt)


def test_stdlib_smoke_image_is_a_valid_red_2_by_3_png():
    from PySide6.QtGui import QImage
    picture = QImage.fromData(module('smoke_bundle').image_fixture(), 'PNG')
    assert not picture.isNull() and (picture.width(), picture.height()) == (2, 3)
    assert picture.pixelColor(1, 2).name() == '#ff0000'


def test_smoke_receipt_requires_editor_creation_and_editing(tmp_path):
    stage = module('stage_candidate')
    receipt = tmp_path / 'result.json'
    data = dict(success=True, rename='passed', undo='passed', originals_unchanged=True,
                hashes_before={'file': 'a'}, hashes_after={'file': 'a'})
    receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='rule creation'):
        stage.check_smoke_report(receipt)
    data.update(rule_creation='passed', rule_editing='passed', created_rule_kinds=['insert', 'replace'])
    data.update(tiff_metadata='passed', tiff_original_unchanged=True)
    receipt.write_text(json.dumps(data))
    assert stage.check_smoke_report(receipt) == data
    for key in ('rule_creation', 'rule_editing', 'created_rule_kinds', 'tiff_metadata', 'tiff_original_unchanged'):
        receipt.write_text(json.dumps(data | {key: None}))
        with pytest.raises(ValueError, match='rule creation'):
            stage.check_smoke_report(receipt)


def linux_receipt(stage, directory):
    names = ['File-Renamer-linux-x86_64.tar.gz', 'File-Renamer-x86_64.AppImage',
             'BUILD-INFO-Linux.json', 'QA-Linux.zip', 'SHA256SUMS-Linux.txt']
    for name in names:
        (directory / name).write_bytes(name.encode())
    return dict(source_commit='a' * 40, source_tree='b' * 40, platform='Linux', run_id='123',
                native_smoke='passed', rule_editor_smoke='passed',
                files=[stage.record(directory / name) for name in names])


def test_retained_linux_receipt_requires_exact_source_run_and_complete_asset_set(monkeypatch, tmp_path):
    stage = module('stage_candidate')
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    receipt = linux_receipt(stage, tmp_path)
    stage.check_receipt(receipt, 'a' * 40, 'b' * 40, 'Linux')
    for mutation in (dict(source_commit='c' * 40), dict(source_tree='c' * 40), dict(run_id='124'),
                     dict(platform='Windows'), dict(rule_editor_smoke=None),
                     dict(files=receipt['files'][:-1]), dict(files=receipt['files'] + receipt['files'][:1])):
        with pytest.raises(ValueError):
            stage.check_receipt(receipt | mutation, 'a' * 40, 'b' * 40, 'Linux')


def test_retained_linux_bytes_are_verified_before_use(tmp_path):
    stage = module('stage_candidate')
    receipt = linux_receipt(stage, tmp_path)
    stage.verify_linux_files(tmp_path, receipt)
    (tmp_path / 'File-Renamer-x86_64.AppImage').write_bytes(b'different bytes')
    with pytest.raises(ValueError, match='checksum mismatch'):
        stage.verify_linux_files(tmp_path, receipt)


def test_ubuntu24_evidence_is_invalidated_when_retained_linux_receipt_changes(tmp_path):
    stage = module('stage_candidate')
    linux = tmp_path / 'RELEASE-Linux.json'
    linux.write_text(json.dumps(linux_receipt(stage, tmp_path)))
    ubuntu24 = {'verified_inputs': {'RELEASE-Linux.json': stage.record(linux)['sha256']}}
    stage.check_compatibility_input(ubuntu24, linux)
    linux.write_text(linux.read_text() + '\n')
    with pytest.raises(ValueError, match='currently retained Linux build'):
        stage.check_compatibility_input(ubuntu24, linux)


@pytest.mark.parametrize('name,link', [('outside', None), ('File-Renamer/../../outside', None),
                                      ('File-Renamer/link', '../../outside')])
def test_portable_archive_cannot_escape_bundle(tmp_path, name, link):
    stage = module('stage_candidate')
    archive_path = tmp_path / 'unsafe.tar.gz'
    with tarfile.open(archive_path, 'w:gz') as archive:
        entry = tarfile.TarInfo(name)
        if link:
            entry.type = tarfile.SYMTYPE
            entry.linkname = link
        archive.addfile(entry)
    with pytest.raises(ValueError):
        stage.extract_bundle(archive_path, tmp_path / 'extract')
    assert not (tmp_path / 'outside').exists()


def test_portable_archive_keeps_safe_bundle_contents(tmp_path):
    stage = module('stage_candidate')
    archive_path = tmp_path / 'safe.tar.gz'
    with tarfile.open(archive_path, 'w:gz') as archive:
        entry = tarfile.TarInfo('File-Renamer/File-Renamer')
        entry.size = len(b'package')
        archive.addfile(entry, io.BytesIO(b'package'))
    stage.extract_bundle(archive_path, tmp_path / 'extract')
    assert (tmp_path / 'extract/File-Renamer/File-Renamer').read_bytes() == b'package'


def test_candidate_requires_nonempty_passing_tests(tmp_path):
    stage = module('stage_candidate')
    report = tmp_path / 'tests.xml'
    report.write_text('<testsuites><testsuite tests="3" failures="0" errors="0" skipped="1"/></testsuites>')
    assert stage.check_test_report(report) == dict(tests=3, failures=0, errors=0, skipped=1)
    for attribute in ('failures', 'errors'):
        report.write_text(f'<testsuites><testsuite tests="3" {attribute}="1"/></testsuites>')
        with pytest.raises(ValueError):
            stage.check_test_report(report)
    report.write_text('<testsuites/>')
    with pytest.raises(ValueError):
        stage.check_test_report(report)


def test_public_provenance_does_not_include_remote_credentials():
    source = (ROOT / 'scripts/build_manifest.py').read_text()
    assert 'git("remote", "get-url"' not in source
    assert '"repository": "steadystatestudio/file-renamer-releases"' in source


def test_public_links_use_release_repositories():
    import re

    paths = [ROOT / 'README.md', ROOT / 'THIRD_PARTY_NOTICES.md', ROOT / 'docs/index.html']
    for path in paths:
        assert not re.search(r'https://github\.com/steadystatestudio/(?:file-renamer|square-photo-padder)(?:[/#)"\s]|$)',
                             path.read_text())
    page = (ROOT / 'docs/index.html').read_text()
    assert 'requires sign-in' not in page
    assert 'completed build runs' not in page


def test_duplicate_tag_blocks_selected_draft(monkeypatch):
    stage = module('stage_candidate')
    release = dict(id=123, draft=True, prerelease=True, tag_name='v2.0.3',
                   target_commitish='a' * 40, assets=[])
    monkeypatch.setenv('RELEASE_ID', '123')
    monkeypatch.setattr(stage, 'identity', lambda: ('a' * 40, 'b' * 40, 'v2.0.3'))
    monkeypatch.setattr(stage, 'api', lambda *_: release)
    monkeypatch.setattr(stage, 'release_inventory', lambda: [release, release | {'id': 456}])
    with pytest.raises(ValueError, match='uniquely'):
        stage.current_release()


def test_draft_restaging_invalidates_ready_before_upload(monkeypatch, tmp_path):
    stage = module('stage_candidate')
    release = dict(tag_name='v2.0.3', assets=[dict(name='RELEASE-READY.json', id=99)])
    monkeypatch.setattr(stage, 'current_release', lambda: release)
    calls = []
    monkeypatch.setattr(stage.subprocess, 'run', lambda command, **kwargs: calls.append(command))
    archive = tmp_path / 'QA-Windows.zip'
    archive.write_bytes(b'rebuilt QA bytes')
    stage.upload([archive])
    assert calls[0][-1].endswith('/releases/assets/99')
    assert '--method' in calls[0] and 'DELETE' in calls[0]
    assert calls[1][:3] == ['gh', 'release', 'upload'] and '--clobber' in calls[1]


def test_published_release_blocks_upload_before_mutation(monkeypatch, tmp_path):
    stage = module('stage_candidate')
    release = dict(id=123, draft=False, prerelease=False, tag_name='v2.0.3',
                   target_commitish='a' * 40, assets=[])
    monkeypatch.setenv('RELEASE_ID', '123')
    monkeypatch.setattr(stage, 'identity', lambda: ('a' * 40, 'b' * 40, 'v2.0.3'))
    monkeypatch.setattr(stage, 'api', lambda *_: release)
    monkeypatch.setattr(stage.subprocess, 'run', lambda *a, **k: pytest.fail('Unexpected mutation'))
    with pytest.raises(ValueError, match='draft prerelease'):
        stage.upload([tmp_path / 'anything'])
