import importlib.util
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
    import json
    stage = module('stage_candidate')
    receipt = tmp_path / 'result.json'
    data = dict(success=True, rename='passed', undo='passed', originals_unchanged=True,
                hashes_before={'file': 'a'}, hashes_after={'file': 'b'})
    receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='verification'):
        stage.check_smoke_report(receipt)


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


def test_public_docs_do_not_link_private_development_repositories():
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
