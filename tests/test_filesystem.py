import os
from dataclasses import replace
from pathlib import Path

import pytest

from file_renamer.filesystem import name_error, scan_paths
from file_renamer.models import RuleSpec
from file_renamer.planner import build_plan


def test_scan_recursive_and_deduplicate(make_entry, tmp_path):
    a, b = make_entry("a.txt"), make_entry("child/b.txt")
    entries, errors = scan_paths([str(tmp_path)], False)
    assert not errors
    assert {entry.path for entry in entries} == {a.path}
    entries, errors = scan_paths([str(tmp_path), a.path], True)
    assert not errors
    assert {entry.path for entry in entries} == {a.path, b.path}


def test_scan_skips_links(make_entry, tmp_path):
    a = make_entry("a.txt")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(a.path)
    except OSError:
        pytest.skip("Symlink privilege is not available")
    entries, errors = scan_paths([str(link)], True)
    assert not entries and errors


def test_collisions_and_unchanged_occupant(make_entry):
    a, b = make_entry("a.txt"), make_entry("b.txt")
    rule = RuleSpec("replace", options={"find": "a", "replacement": "b"})
    assert build_plan([a], [rule]).errors
    assert len(build_plan([a, b], [rule]).errors) == 2
    assert build_plan([a, replace(b, included=False)], [rule]).errors


def test_preview_is_read_only_and_changed_source_fails(make_entry):
    entry = make_entry("a.txt")
    before = Path(entry.path).read_bytes()
    plan = build_plan([entry], [RuleSpec("insert", options={"text": "new_"})])
    assert plan.changes and Path(entry.path).read_bytes() == before
    assert not Path(plan.files[0].destination).exists()
    Path(entry.path).write_bytes(b"different content")
    assert build_plan([entry], []).errors


@pytest.mark.skipif(os.name != "nt", reason="Windows naming policy")
@pytest.mark.parametrize("name", ["CON.txt", "nul", "bad?.txt", "trailing. ", "LPT1.txt", "a" * 256])
def test_windows_invalid_names(tmp_path, name):
    assert name_error(tmp_path / name)


@pytest.mark.parametrize("recursive", [False, True])
def test_hidden_paths_are_excluded(make_entry, tmp_path, recursive):
    visible = make_entry("visible.txt")
    hidden = make_entry(".secret")
    child = make_entry(".private/child.txt")
    entries, errors = scan_paths([str(tmp_path), hidden.path, child.path], recursive)
    assert [entry.path for entry in entries] == [visible.path]
    assert errors and all("Skipped hidden item:" in error for error in errors)
    assert build_plan([hidden, child], []).errors


@pytest.mark.skipif(os.name != "nt", reason="Windows file attributes")
@pytest.mark.parametrize("attribute", [2, 4])
def test_windows_hidden_system_files(make_entry, tmp_path, attribute):
    import ctypes

    entry = make_entry("desktop.ini")
    setter = ctypes.windll.kernel32.SetFileAttributesW
    assert setter(entry.path, attribute)
    try:
        entries, errors = scan_paths([str(tmp_path), entry.path], True)
        assert not entries and errors
        assert build_plan([entry], []).errors
    finally:
        assert setter(entry.path, 128)
