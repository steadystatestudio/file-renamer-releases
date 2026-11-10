"""Files must never be left hidden, stranded or unrestorable by a rename batch."""
import json
import os
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from file_renamer import filesystem
from file_renamer.filesystem import regular_identity, rename_no_replace, scan_paths
from file_renamer.models import PlannedFile, RenamePlan, RuleSpec
from file_renamer.planner import build_plan
from file_renamer.storage import atomic_json
from file_renamer.transactions import TransactionManager, is_temporary_name, temporary_name


def record_moves(monkeypatch):
    moves = []

    def spy(source, target):
        moves.append((Path(source).name, Path(target).name))
        rename_no_replace(source, target)

    monkeypatch.setattr("file_renamer.transactions.rename_no_replace", spy)
    return moves


def unstable_ids(monkeypatch, start_after=0):
    """Report a new inode for every lookup, as FAT/exFAT do after cache eviction."""
    calls = [0]

    def shifted(path):
        found = regular_identity(path)
        calls[0] += 1
        return found if calls[0] <= start_after else replace(found, inode=found.inode + calls[0])

    monkeypatch.setattr(filesystem, "regular_identity", shifted)
    monkeypatch.setattr("file_renamer.transactions.regular_identity", shifted)


def test_ordinary_batch_moves_each_file_once_without_staging(make_entry, tmp_path, monkeypatch):
    entries = [make_entry(f"{index}.flac") for index in range(4)]
    plan = build_plan(entries, [RuleSpec("insert", options={"text": "new_"})])
    moves = record_moves(monkeypatch)
    assert TransactionManager(tmp_path / "data" / "journal.json").execute(plan).success
    assert sorted(moves) == [(f"{index}.flac", f"new_{index}.flac") for index in range(4)]


def test_chain_is_ordered_instead_of_staged(make_entry, tmp_path, monkeypatch):
    a, b = make_entry("a.txt", b"A"), make_entry("b.txt", b"B")
    plan = RenamePlan(1, (PlannedFile(a, b.path), PlannedFile(b, str(tmp_path / "c.txt"))))
    moves = record_moves(monkeypatch)
    manager = TransactionManager(tmp_path / "data" / "journal.json")
    assert manager.execute(plan).success
    assert moves == [("b.txt", "c.txt"), ("a.txt", "b.txt")]
    assert (tmp_path / "b.txt").read_bytes() == b"A" and (tmp_path / "c.txt").read_bytes() == b"B"
    assert manager.restore().success
    assert Path(a.path).read_bytes() == b"A" and Path(b.path).read_bytes() == b"B"


def test_swap_stages_one_file_under_a_visible_name_with_its_extension(make_entry, tmp_path, monkeypatch):
    a, b = make_entry("Song A.flac", b"A"), make_entry("Song B.flac", b"B")
    plan = RenamePlan(1, (PlannedFile(a, b.path), PlannedFile(b, a.path)))
    moves = record_moves(monkeypatch)
    assert TransactionManager(tmp_path / "data" / "journal.json").execute(plan).success
    staged = [target for _, target in moves if is_temporary_name(target)]
    assert len(moves) == 3 and len(staged) == 1
    assert staged[0].startswith("Song ") and staged[0].endswith(".flac")
    assert Path(a.path).read_bytes() == b"B" and Path(b.path).read_bytes() == b"A"


def test_temporary_names_stay_visible_recognizable_and_within_the_limit():
    name = temporary_name("/music/01. Title.flac", "ab" * 8)
    assert name == "01. Title.file-renamer-abababababababab.flac" and is_temporary_name(name)
    long_name = temporary_name("/music/" + "é" * 200 + ".flac", "ab" * 8)
    assert len(os.fsencode(long_name)) <= 255 and long_name.endswith(".flac") and long_name.startswith("é")
    assert not temporary_name("/music/.hidden", "ab" * 8).startswith(".")
    assert is_temporary_name(".file-renamer-" + "0" * 32 + ".tmp")  # Staging name used through 2.2.9.
    assert not is_temporary_name("my.file-renamer-notes.txt")


def test_changing_file_ids_do_not_block_or_strand_a_batch(make_entry, tmp_path, monkeypatch):
    entries = [make_entry(f"{index:02d} track.flac", f"audio {index}".encode()) for index in range(5)]
    plan = build_plan(entries, [RuleSpec("insert", options={"text": "x_"})])
    monkeypatch.setattr(filesystem, "stable_file_ids", lambda _: False)
    unstable_ids(monkeypatch)
    manager = TransactionManager(tmp_path / "data" / "journal.json")
    result = manager.execute(plan)
    assert result.success, result.message
    assert sorted(path.name for path in tmp_path.glob("*.flac")) == [f"x_{i:02d} track.flac" for i in range(5)]
    restored = manager.restore()
    assert restored.success, restored.message
    assert all(Path(entry.path).read_bytes() == f"audio {i}".encode() for i, entry in enumerate(entries))


def test_changed_ids_on_a_stable_filesystem_leave_every_original_in_place(make_entry, tmp_path, monkeypatch):
    entries = [make_entry(f"{index}.flac") for index in range(3)]
    plan = build_plan(entries, [RuleSpec("insert", options={"text": "x_"})])
    monkeypatch.setattr(filesystem, "stable_file_ids", lambda _: True)
    unstable_ids(monkeypatch)
    result = TransactionManager(tmp_path / "data" / "journal.json").execute(plan)
    assert not result.success and not result.recovery_required
    assert sorted(path.name for path in tmp_path.glob("*.flac")) == ["0.flac", "1.flac", "2.flac"]


def test_undo_restores_every_file_it_can_and_reports_the_rest(make_entry, tmp_path):
    entries = [make_entry(f"{index}.flac", f"audio {index}".encode()) for index in range(3)]
    plan = build_plan(entries, [RuleSpec("insert", options={"text": "x_"})])
    manager = TransactionManager(tmp_path / "data" / "journal.json")
    assert manager.execute(plan).success
    (tmp_path / "x_1.flac").write_bytes(b"edited by another program, different length")
    result = manager.restore()
    assert not result.success and result.recovery_required
    assert "x_1.flac" in result.message
    assert sorted(path.name for path in tmp_path.glob("*.flac")) == ["0.flac", "2.flac", "x_1.flac"]
    assert (tmp_path / "x_1.flac").read_bytes().startswith(b"edited")
    # Nothing is lost by asking again; the outstanding file is still reported.
    again = manager.restore()
    assert not again.success and "x_1.flac" in again.message


def test_recover_restores_files_stranded_under_hidden_names_by_2_2_9(tmp_path):
    folder = tmp_path / "album"
    folder.mkdir()
    records = []
    for index in range(3):
        hidden = folder / f".file-renamer-{index:032x}.tmp"
        hidden.write_bytes(f"audio {index}".encode())
        identity = asdict(regular_identity(hidden))
        # The identity recorded at scan time no longer matches (FAT/exFAT inode renumbering).
        identity["inode"] += 1000
        identity["device"] += 1
        records.append({"original": str(folder / f"0{index}. Song.flac"),
                        "target": str(folder / f"{index} Song.flac"),
                        "current": str(hidden), "identity": identity})
    journal = tmp_path / "data" / "last-rename.json"
    journal.parent.mkdir()
    atomic_json(journal, {"version": 1, "transaction": "a" * 32, "sequence": 0, "status": "needs_recovery",
                          "pending": None, "records": records})
    result = TransactionManager(journal).restore()
    assert result.success, result.message
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == {
        f"0{index}. Song.flac": f"audio {index}".encode() for index in range(3)}
    assert json.loads(journal.read_text(encoding="utf-8"))["status"] == "rolled_back"


def test_scan_names_files_left_by_an_interrupted_rename(tmp_path):
    stranded = tmp_path / (".file-renamer-" + "0" * 32 + ".tmp")
    stranded.write_bytes(b"audio")
    entries, errors = scan_paths([str(tmp_path)], False)
    assert not entries and "interrupted rename" in errors[0] and str(stranded) in errors[0]


def test_recovery_log_shared_with_another_file_is_never_truncated(make_entry, tmp_path):
    entry = make_entry("a.flac")
    plan = build_plan([entry], [RuleSpec("insert", options={"text": "x_"})])
    victim = tmp_path / "victim.flac"
    victim.write_bytes(b"precious audio")
    journal = tmp_path / "data" / "journal.json"
    journal.parent.mkdir()
    try:
        os.link(victim, journal.with_suffix(".log"))
    except OSError:
        pytest.skip("filesystem has no hard links")
    result = TransactionManager(journal).execute(plan)
    assert not result.success
    assert victim.read_bytes() == b"precious audio"
    assert Path(entry.path).exists()


def test_case_probe_reads_the_directory_itself(tmp_path):
    (tmp_path / "Track.flac").write_bytes(b"audio")
    # FAT, exFAT and NTFS folders answer to either spelling; ext4 normally does not.
    assert filesystem._probe_case_sensitive(tmp_path) == (not (tmp_path / "tRACK.FLAC").exists())
    assert filesystem._probe_case_sensitive(tmp_path / "missing") is True


@pytest.mark.skipif(os.name == "nt", reason="mount table is a Linux interface")
def test_mount_table_names_the_filesystem_and_decodes_escaped_mount_points(tmp_path, monkeypatch):
    assert filesystem.filesystem_type(tmp_path)
    table = ("36 25 8:1 / / rw - ext4 /dev/sda1 rw\n"
             "90 36 8:17 / /media/user/MUSIC\\040DRIVE rw - exfat /dev/sdb1 rw\n")
    import io
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(table))
    assert filesystem._linux_filesystem_type("/media/user/MUSIC DRIVE/album") == "exfat"
    assert filesystem._linux_filesystem_type("/home/user/Music") == "ext4"
