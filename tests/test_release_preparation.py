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
