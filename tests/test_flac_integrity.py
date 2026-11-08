"""Real FLAC preservation under ordinary rename, cancellation and process exit."""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from file_renamer.filesystem import regular_identity
from file_renamer.models import FileEntry, PlannedFile, RenamePlan, RuleSpec
from file_renamer.planner import build_plan
from file_renamer.smoke import flac_fixture
from file_renamer.transactions import TransactionManager


def album(root):
    folder = root / "album"
    folder.mkdir()
    tracks = {
        "01. First Song.flac": flac_fixture(title="First Song"),
        "02. Café’s Song.flac": flac_fixture(title="Café’s Song"),
        "03. Last Song.flac": flac_fixture(title="Last Song"),
    }
    for name, audio in tracks.items():
        (folder / name).write_bytes(audio)
    entries = [FileEntry(str(folder / name), regular_identity(folder / name)) for name in tracks]
    return folder, tracks, entries


def verify_album(folder, tracks):
    assert set(path.name for path in folder.iterdir()) == set(tracks)
    assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir()} == {
        name: hashlib.sha256(audio).hexdigest() for name, audio in tracks.items()
    }


def test_flac_album_rename_then_restart_undo(tmp_path):
    folder, tracks, entries = album(tmp_path)
    plan = build_plan(entries, [RuleSpec("insert", options={"text": "renamed_"})])
    journal = tmp_path / "data" / "last-rename.json"
    result = TransactionManager(journal).execute(plan)
    assert result.success, result.message
    verify_album(folder, {"renamed_" + name: audio for name, audio in tracks.items()})
    result = TransactionManager(journal).restore()
    assert result.success, result.message
    verify_album(folder, tracks)


@pytest.mark.parametrize("stop_after", range(1, 7))
def test_flac_album_cancel_restores_originals(tmp_path, stop_after):
    folder, tracks, entries = album(tmp_path)
    plan = build_plan(entries, [RuleSpec("insert", options={"text": "renamed_"})])
    complete = [0]
    result = TransactionManager(tmp_path / "journal.json").execute(
        plan, lambda: complete[0] >= stop_after,
        lambda done, total: complete.__setitem__(0, done),
    )
    if stop_after == 6:
        assert result.success, result.message
        assert TransactionManager(tmp_path / "journal.json").restore().success
    else:
        assert not result.success and not result.recovery_required, result.message
    verify_album(folder, tracks)


@pytest.mark.parametrize("exit_after", range(1, 7))
def test_real_process_exit_at_each_flac_move_recovers(tmp_path, exit_after):
    folder, tracks, entries = album(tmp_path)
    journal = tmp_path / "data" / "last-rename.json"
    probe = r'''
import os
import sys
from pathlib import Path
from file_renamer import transactions
from file_renamer.filesystem import regular_identity
from file_renamer.models import FileEntry, RuleSpec
from file_renamer.planner import build_plan
folder, journal, stop = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
entries = [FileEntry(str(p), regular_identity(p)) for p in sorted(folder.iterdir())]
plan = build_plan(entries, [RuleSpec("insert", options={"text": "renamed_"})])
original = transactions.rename_no_replace
count = 0
def exit_after_move(source, target):
    global count
    original(source, target)
    count += 1
    if count == stop:
        os._exit(91)
transactions.rename_no_replace = exit_after_move
transactions.TransactionManager(journal).execute(plan)
raise AssertionError("Process did not exit during a move")
'''
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    stopped = subprocess.run(
        [sys.executable, "-c", probe, str(folder), str(journal), str(exit_after)],
        env=environment, capture_output=True, text=True, timeout=30,
    )
    assert stopped.returncode == 91, stopped.stdout + stopped.stderr
    # All audio still exists after abrupt process exit, including staged entries.
    assert sorted(hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir()) == sorted(
        hashlib.sha256(audio).hexdigest() for audio in tracks.values()
    )
    restored = TransactionManager(journal).restore()
    assert restored.success, restored.message
    verify_album(folder, tracks)


def test_flac_collision_preserves_both_tracks(tmp_path):
    folder, tracks, entries = album(tmp_path)
    plan = RenamePlan(1, (PlannedFile(entries[0], entries[1].path),))
    result = TransactionManager(tmp_path / "journal.json").execute(plan)
    assert not result.success and not result.recovery_required
    verify_album(folder, tracks)


def test_hidden_flac_output_keeps_audio_and_restart_undo(tmp_path):
    folder, tracks, entries = album(tmp_path)
    plan = build_plan(entries, [RuleSpec("insert", options={"text": "."})])
    journal = tmp_path / "journal.json"
    result = TransactionManager(journal).execute(plan)
    assert result.success, result.message
    verify_album(folder, {"." + name: audio for name, audio in tracks.items()})
    assert TransactionManager(journal).restore().success
    verify_album(folder, tracks)
