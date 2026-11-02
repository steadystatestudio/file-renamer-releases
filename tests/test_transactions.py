import json
from dataclasses import asdict
from pathlib import Path

import pytest

from file_renamer.filesystem import rename_no_replace
from file_renamer.models import PlannedFile, RenamePlan, RuleSpec
from file_renamer.planner import build_plan
from file_renamer.storage import atomic_json
from file_renamer.transactions import TransactionManager


def test_execute_and_undo_survive_restart(make_entry, tmp_path):
    entry = make_entry("original.txt")
    plan = build_plan([entry], [RuleSpec("insert", options={"text": "new_"})])
    manager = TransactionManager(tmp_path / "data" / "last-rename.json")
    result = manager.execute(plan)
    assert result.success, result.message
    assert not Path(entry.path).exists()
    assert Path(plan.files[0].destination).read_bytes() == b"test content"
    restored = TransactionManager(manager.journal).restore()
    assert restored.success, restored.message
    assert Path(entry.path).read_bytes() == b"test content"


def test_swaps_and_case_only(make_entry, tmp_path):
    a, b = make_entry("a.txt", b"AAA"), make_entry("b.txt", b"BBB")
    manager = TransactionManager(tmp_path / "journal.json")
    plan = RenamePlan(1, (PlannedFile(a, b.path), PlannedFile(b, a.path)))
    assert manager.execute(plan).success
    assert Path(a.path).read_bytes() == b"BBB"
    assert Path(b.path).read_bytes() == b"AAA"
    assert manager.restore().success
    upper = str(Path(a.path).with_name("A.txt"))
    assert manager.execute(RenamePlan(2, (PlannedFile(a, upper),))).success
    assert Path(upper).read_bytes() == b"AAA"
    assert manager.restore().success


def test_changed_source_and_destination_race(make_entry, tmp_path, monkeypatch):
    entry = make_entry("a.txt", b"AAA")
    plan = build_plan([entry], [RuleSpec("insert", options={"text": "new_"})])
    manager = TransactionManager(tmp_path / "journal.json")
    original = rename_no_replace

    def race(source, target):
        if target == plan.files[0].destination:
            Path(target).write_bytes(b"outsider")
        original(source, target)

    monkeypatch.setattr("file_renamer.transactions.rename_no_replace", race)
    result = manager.execute(plan)
    assert not result.success and not result.recovery_required
    assert Path(entry.path).read_bytes() == b"AAA"
    assert Path(plan.files[0].destination).read_bytes() == b"outsider"


def test_cancel_rolls_back(make_entry, tmp_path):
    entries = [make_entry(f"{index}.txt") for index in range(4)]
    plan = build_plan(entries, [RuleSpec("insert", options={"text": "new_"})])
    cancel = [False]
    manager = TransactionManager(tmp_path / "journal.json")
    result = manager.execute(plan, lambda: cancel[0], lambda *_: cancel.__setitem__(0, True))
    assert not result.success and not result.recovery_required
    assert all(Path(entry.path).exists() for entry in entries)
    assert not list(tmp_path.glob(".file-renamer-*.tmp"))


def test_permission_failure_rolls_back(make_entry, tmp_path, monkeypatch):
    entries = [make_entry(f"{index}.txt") for index in range(3)]
    plan = build_plan(entries, [RuleSpec("insert", options={"text": "new_"})])
    calls = [0]

    def fail_once(source, target):
        calls[0] += 1
        if calls[0] == 2:
            raise PermissionError("Simulated locked file")
        rename_no_replace(source, target)

    monkeypatch.setattr("file_renamer.transactions.rename_no_replace", fail_once)
    result = TransactionManager(tmp_path / "journal.json").execute(plan)
    assert not result.success and not result.recovery_required
    assert all(Path(entry.path).exists() for entry in entries)


def test_recover_crash_between_move_and_journal_update(make_entry, tmp_path):
    entry = make_entry("a.txt", b"original")
    temporary = str(tmp_path / ".file-renamer-interrupted.tmp")
    journal = tmp_path / "data" / "last-rename.json"
    data = {"version": 1, "transaction": "crash", "sequence": 0, "status": "active",
            "pending": {"index": 0, "from": entry.path, "to": temporary}, "records": [
                {"original": entry.path, "target": str(tmp_path / "b.txt"), "current": entry.path,
                 "identity": asdict(entry.identity)}]}
    atomic_json(journal, data)
    rename_no_replace(entry.path, temporary)
    assert TransactionManager(journal).restore().success
    assert Path(entry.path).read_bytes() == b"original"
    assert not Path(temporary).exists()


def test_undo_conflict_and_external_change_are_preserved(make_entry, tmp_path):
    entry = make_entry("a.txt", b"original")
    plan = build_plan([entry], [RuleSpec("insert", options={"text": "new_"})])
    manager = TransactionManager(tmp_path / "journal.json")
    assert manager.execute(plan).success
    Path(entry.path).write_bytes(b"outsider")
    result = manager.restore()
    assert not result.success and result.recovery_required
    assert Path(entry.path).read_bytes() == b"outsider"
    Path(entry.path).unlink()
    assert manager.restore().success
    # Re-add the file to refresh identity before the next transaction.
    from file_renamer.filesystem import scan_paths
    entries, _ = scan_paths([entry.path], False)
    assert manager.execute(build_plan(entries, [RuleSpec("insert", options={"text": "new_"})])).success
    Path(plan.files[0].destination).write_bytes(b"edited after rename")
    assert not manager.restore().success
    assert Path(plan.files[0].destination).read_bytes() == b"edited after rename"


def test_no_replace_directly(make_entry, tmp_path):
    a, b = make_entry("a", b"A"), make_entry("b", b"B")
    with pytest.raises(OSError):
        rename_no_replace(a.path, b.path)
    assert Path(a.path).read_bytes() == b"A"
    assert Path(b.path).read_bytes() == b"B"


def test_corrupt_journal_blocks_mutation(make_entry, tmp_path):
    entry = make_entry("a.txt")
    journal = tmp_path / "journal.json"
    journal.write_text(json.dumps({"version": 99}), encoding="utf-8")
    with pytest.raises(ValueError):
        TransactionManager(journal).execute(build_plan([entry], [RuleSpec("case")]))
    assert Path(entry.path).exists()


@pytest.mark.parametrize("crash_after", range(1, 7))
def test_recover_every_phase_of_three_file_cycle(make_entry, tmp_path, monkeypatch, crash_after):
    entries = [make_entry(f"{i}.txt", str(i).encode()) for i in range(3)]
    plan = RenamePlan(1, tuple(PlannedFile(entry, entries[(i + 1) % 3].path) for i, entry in enumerate(entries)))
    calls = [0]

    def crash(source, target):
        rename_no_replace(source, target)
        calls[0] += 1
        if calls[0] == crash_after:
            raise SystemExit("Simulated process termination after move, before completion log")

    monkeypatch.setattr("file_renamer.transactions.rename_no_replace", crash)
    journal = tmp_path / "journal.json"
    with pytest.raises(SystemExit):
        TransactionManager(journal).execute(plan)
    monkeypatch.setattr("file_renamer.transactions.rename_no_replace", rename_no_replace)
    result = TransactionManager(journal).restore()
    assert result.success, result.message
    assert all(Path(entry.path).read_bytes() == str(i).encode() for i, entry in enumerate(entries))
    assert not list(tmp_path.glob(".file-renamer-*.tmp"))


def test_completion_log_failure_and_torn_tail(make_entry, tmp_path, monkeypatch):
    entry = make_entry("a.txt")
    plan = build_plan([entry], [RuleSpec("insert", options={"text": "new_"})])
    manager = TransactionManager(tmp_path / "journal.json")
    append = manager._append
    calls = [0]

    def fail(data, event):
        calls[0] += 1
        if calls[0] == 2:
            with manager.journal.with_suffix(".log").open("ab") as handle:
                handle.write(b'{"incomplete":')
            raise OSError("Simulated interrupted journal append")
        append(data, event)

    monkeypatch.setattr(manager, "_append", fail)
    result = manager.execute(plan)
    assert not result.success and not result.recovery_required, result.message
    assert Path(entry.path).exists()
    assert manager.load()["status"] == "rolled_back"


def test_revalidate_missing_or_modified_source(make_entry, tmp_path):
    entry = make_entry("a.txt")
    plan = build_plan([entry], [RuleSpec("insert", options={"text": "new_"})])
    Path(entry.path).write_bytes(b"modified externally")
    manager = TransactionManager(tmp_path / "journal.json")
    assert not manager.execute(plan).success
    assert Path(entry.path).read_bytes() == b"modified externally"
    Path(entry.path).unlink()
    assert not manager.execute(plan).success
    assert not manager.journal.exists()


def test_hidden_source_rechecked_before_execute(make_entry, tmp_path, monkeypatch):
    entry = make_entry("original.txt")
    plan = build_plan([entry], [RuleSpec("insert", options={"text": "new_"})])
    monkeypatch.setattr("file_renamer.planner.hidden_path", lambda _: True)
    result = TransactionManager(tmp_path / "journal.json").execute(plan)
    assert not result.success
    assert Path(entry.path).exists()
    assert not Path(plan.files[0].destination).exists()


def test_undo_can_restore_hidden_destination(make_entry, tmp_path):
    entry = make_entry("original.txt")
    plan = build_plan([entry], [RuleSpec("insert", options={"text": "."})])
    manager = TransactionManager(tmp_path / "journal.json")
    assert manager.execute(plan).success
    assert manager.restore().success
    assert Path(entry.path).read_bytes() == b"test content"
