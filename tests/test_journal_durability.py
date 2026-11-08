"""Recovery state must be durable and usable before the first source move."""

import errno
import os
import stat
from dataclasses import asdict
from pathlib import Path

import pytest

from file_renamer import storage, transactions
from file_renamer.models import RuleSpec
from file_renamer.planner import build_plan
from file_renamer.transactions import TransactionManager

linux_only = pytest.mark.skipif(os.name == "nt", reason="Linux directory fsync contract")


def _same_file(info, path):
    if not path.exists():
        return False
    expected = path.stat()
    return (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino)


def _plan(entry):
    return build_plan([entry], [RuleSpec("insert", options={"text": "new_"})])


@linux_only
def test_log_name_is_synced_after_creation_before_any_source_move(make_entry, tmp_path, monkeypatch):
    entry = make_entry("album/01. Song.flac", b"fLaC synthetic fixture")
    manager = TransactionManager(tmp_path / "data" / "last-rename.json")
    log = manager.journal.with_suffix(".log")
    actual_fsync = os.fsync
    actual_rename = transactions.rename_no_replace
    log_synced = False
    log_name_synced = False
    moves = []

    def fsync(descriptor):
        nonlocal log_synced, log_name_synced
        info = os.fstat(descriptor)
        actual_fsync(descriptor)
        if stat.S_ISREG(info.st_mode) and _same_file(info, log):
            log_synced = True
        elif stat.S_ISDIR(info.st_mode) and log_synced and _same_file(info, log.parent):
            log_name_synced = True

    def rename(source, target):
        assert log_synced and log_name_synced, "Log contents and name must precede source moves"
        moves.append((source, target))
        actual_rename(source, target)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(transactions, "rename_no_replace", rename)
    result = manager.execute(_plan(entry))
    assert result.success, result.message
    assert len(moves) == 2
    assert manager.restore().success
    assert Path(entry.path).read_bytes() == b"fLaC synthetic fixture"


@linux_only
def test_directory_sync_rejection_preserves_flac_and_previous_undo(make_entry, tmp_path, monkeypatch):
    prior = make_entry("previous/old.flac", b"fLaC prior fixture")
    manager = TransactionManager(tmp_path / "data" / "last-rename.json")
    prior_plan = _plan(prior)
    assert manager.execute(prior_plan).success
    prior_journal = manager.journal.read_bytes()
    prior_log = manager.journal.with_suffix(".log").read_bytes()
    entries = [make_entry(f"album/{index:02}. Song.flac", b"fLaC fixture " + bytes([index])) for index in range(3)]
    album = Path(entries[0].path).parent
    contents = {entry.path: Path(entry.path).read_bytes() for entry in entries}
    plan = build_plan(entries, [RuleSpec("insert", options={"text": "new_"})])
    actual_fsync = os.fsync
    actual_rename = transactions.rename_no_replace
    moves = []

    def rename(source, target):
        moves.append((source, target))
        actual_rename(source, target)

    def reject_directory_sync(descriptor):
        if _same_file(os.fstat(descriptor), album):
            raise OSError(errno.EINVAL, "Directory syncing is unsupported by this test filesystem")
        actual_fsync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", reject_directory_sync)
        patch.setattr(transactions, "rename_no_replace", rename)
        result = manager.execute(plan)
    assert not result.success and not result.recovery_required, result.message
    assert "Nothing renamed" in result.message
    assert not moves
    assert {entry.path: Path(entry.path).read_bytes() for entry in entries} == contents
    assert not list(album.glob(".file-renamer-*.tmp"))
    assert manager.journal.read_bytes() == prior_journal
    assert manager.journal.with_suffix(".log").read_bytes() == prior_log
    assert manager.restore().success
    assert Path(prior.path).read_bytes() == b"fLaC prior fixture"


@linux_only
def test_log_directory_sync_failure_restores_previous_checkpoint(make_entry, tmp_path, monkeypatch):
    prior = make_entry("previous/old.flac", b"fLaC prior fixture")
    manager = TransactionManager(tmp_path / "data" / "last-rename.json")
    assert manager.execute(_plan(prior)).success
    previous = manager.load()
    entry = make_entry("album/new.flac", b"fLaC new fixture")
    actual_sync = transactions._sync_directory

    def reject_log_directory(path):
        if path == manager.journal.parent:
            raise OSError(errno.EIO, "Simulated recovery-log directory sync failure")
        actual_sync(path)

    with monkeypatch.context() as patch:
        patch.setattr(transactions, "_sync_directory", reject_log_directory)
        result = manager.execute(_plan(entry))
    assert not result.success and not result.recovery_required, result.message
    assert "Nothing renamed" in result.message
    assert Path(entry.path).read_bytes() == b"fLaC new fixture"
    assert not list(Path(entry.path).parent.glob(".file-renamer-*.tmp"))
    assert manager.load() == previous
    assert manager.restore().success
    assert Path(prior.path).read_bytes() == b"fLaC prior fixture"


@linux_only
def test_first_preparation_failure_does_not_leave_a_recoverable_batch(make_entry, tmp_path, monkeypatch):
    entry = make_entry("album/song.flac", b"fLaC fixture")
    manager = TransactionManager(tmp_path / "data" / "last-rename.json")
    actual_sync = transactions._sync_directory

    def reject_log_directory(path):
        if path == manager.journal.parent:
            raise OSError(errno.EIO, "Simulated recovery-log directory sync failure")
        actual_sync(path)

    monkeypatch.setattr(transactions, "_sync_directory", reject_log_directory)
    result = manager.execute(_plan(entry))
    assert not result.success and not result.recovery_required, result.message
    assert Path(entry.path).read_bytes() == b"fLaC fixture"
    assert manager.load()["status"] == "rolled_back"


@linux_only
def test_undo_sync_rejection_does_not_move_renamed_files(make_entry, tmp_path, monkeypatch):
    entry = make_entry("album/song.flac", b"fLaC fixture")
    manager = TransactionManager(tmp_path / "data" / "last-rename.json")
    plan = _plan(entry)
    assert manager.execute(plan).success
    album = Path(entry.path).parent
    actual_fsync = os.fsync

    def reject_directory_sync(descriptor):
        if _same_file(os.fstat(descriptor), album):
            raise OSError(errno.EINVAL, "Directory syncing is unsupported by this test filesystem")
        actual_fsync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", reject_directory_sync)
        result = manager.restore()
    assert not result.success and result.recovery_required
    assert Path(plan.files[0].destination).read_bytes() == b"fLaC fixture"
    assert not list(album.glob(".file-renamer-*.tmp"))
    assert manager.restore().success
    assert Path(entry.path).read_bytes() == b"fLaC fixture"


@linux_only
def test_new_journal_ancestors_are_synced_before_any_source_move(make_entry, tmp_path, monkeypatch):
    entry = make_entry("album/song.flac", b"fLaC fixture")
    manager = TransactionManager(tmp_path / "new-organization" / "new-app" / "data" / "last-rename.json")
    directory = manager.journal.absolute().parent
    required = (directory, directory.parent, directory.parent.parent, tmp_path)
    actual_fsync = os.fsync
    actual_rename = transactions.rename_no_replace
    synced = set()

    def fsync(descriptor):
        info = os.fstat(descriptor)
        actual_fsync(descriptor)
        if stat.S_ISDIR(info.st_mode):
            synced.update(path for path in required if _same_file(info, path))

    def rename(source, target):
        assert synced == set(required), "New directories and their first existing parent must precede source moves"
        actual_rename(source, target)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(transactions, "rename_no_replace", rename)
    result = manager.execute(_plan(entry))
    assert result.success, result.message
    assert manager.restore().success
    assert Path(entry.path).read_bytes() == b"fLaC fixture"


def test_existing_journal_directory_does_not_require_ancestor_read_access(make_entry, tmp_path, monkeypatch):
    prior = make_entry("previous/old.flac", b"fLaC prior fixture")
    manager = TransactionManager(tmp_path / "organization" / "data" / "last-rename.json")
    assert manager.execute(_plan(prior)).success
    entry = make_entry("album/new.flac", b"fLaC new fixture")
    actual_sync = transactions._sync_directory

    def reject_journal_ancestor(path):
        if path == manager.journal.parent.parent:
            raise PermissionError(errno.EACCES, "Ancestor permits traversal but not directory reads")
        actual_sync(path)

    with monkeypatch.context() as patch:
        patch.setattr(transactions, "_sync_directory", reject_journal_ancestor)
        result = manager.execute(_plan(entry))
        assert result.success, result.message
        assert manager.restore().success
    assert Path(entry.path).read_bytes() == b"fLaC new fixture"
    assert not list(Path(entry.path).parent.glob(".file-renamer-*.tmp"))


@linux_only
def test_rename_and_undo_below_execute_only_ancestor(make_entry, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("Root bypasses directory read permissions")
    ancestor = tmp_path / "traverse-only"
    directory = ancestor / "organization" / "data"
    storage.ensure_directory(directory)
    entry = make_entry("album/song.flac", b"fLaC permission fixture")
    manager = TransactionManager(directory / "last-rename.json")
    original_mode = stat.S_IMODE(ancestor.stat().st_mode)
    ancestor.chmod(0o111)
    try:
        with pytest.raises(PermissionError):
            os.open(ancestor, os.O_RDONLY | os.O_DIRECTORY)
        result = manager.execute(_plan(entry))
        assert result.success, result.message
        assert manager.restore().success
        assert Path(entry.path).read_bytes() == b"fLaC permission fixture"
    finally:
        ancestor.chmod(original_mode)


def test_oversized_initial_batch_preserves_files_and_previous_undo(make_entry, tmp_path, monkeypatch):
    prior = make_entry("previous/old.flac", b"fLaC prior fixture")
    manager = TransactionManager(tmp_path / "data" / "last-rename.json")
    assert manager.execute(_plan(prior)).success
    previous_journal = manager.journal.read_bytes()
    previous_log = manager.journal.with_suffix(".log").read_bytes()
    entries = [make_entry(f"album/{index:02}. Song.flac", b"fLaC fixture " + bytes([index])) for index in range(8)]
    contents = {entry.path: Path(entry.path).read_bytes() for entry in entries}
    plan = build_plan(entries, [RuleSpec("insert", options={"text": "new_"})])

    def unexpected_save(data):
        raise AssertionError("Oversized initial data must be rejected before journal writes")

    with monkeypatch.context() as patch:
        patch.setattr(storage, "MAX_JSON_BYTES", len(previous_journal))
        patch.setattr(manager, "_save", unexpected_save)
        result = manager.execute(plan)
    assert not result.success and not result.recovery_required, result.message
    assert "Nothing renamed" in result.message and "too large" in result.message
    assert manager.journal.read_bytes() == previous_journal
    assert manager.journal.with_suffix(".log").read_bytes() == previous_log
    assert {entry.path: Path(entry.path).read_bytes() for entry in entries} == contents
    assert not list(Path(entries[0].path).parent.glob(".file-renamer-*.tmp"))
    assert manager.restore().success
    assert Path(prior.path).read_bytes() == b"fLaC prior fixture"


def _initial_snapshot(plan):
    return {
        "version": 1, "transaction": "0" * 32, "sequence": 0,
        "status": "active", "pending": None,
        "records": [
            {"original": row.entry.path, "target": row.destination, "current": row.entry.path,
             "identity": asdict(row.entry.identity)} for row in plan.changes
        ],
    }


def test_initial_fit_with_oversized_later_checkpoint_is_rejected_before_writes(make_entry, tmp_path, monkeypatch):
    entry = make_entry("album/song.flac", b"fLaC fixture")
    plan = build_plan([entry], [RuleSpec("insert", options={"text": "x" * 150})])
    manager = TransactionManager(tmp_path / "data" / "last-rename.json")
    initial_size = len(storage.serialize_json(_initial_snapshot(plan)).encode("utf-8"))
    monkeypatch.setattr(storage, "MAX_JSON_BYTES", initial_size + 32)

    def unexpected_save(data):
        raise AssertionError("Recovery capacity must be reserved before any writes")

    monkeypatch.setattr(manager, "_save", unexpected_save)
    result = manager.execute(plan)
    assert not result.success and not result.recovery_required, result.message
    assert "Nothing renamed" in result.message and "too large" in result.message
    assert Path(entry.path).read_bytes() == b"fLaC fixture"
    assert not Path(plan.files[0].destination).exists()
    assert not list(Path(entry.path).parent.glob(".file-renamer-*.tmp"))
    assert not manager.journal.parent.exists()


@pytest.mark.parametrize("prefix", ["new_", "猫" * 60])
def test_reserved_capacity_allows_crash_replay_and_restart_restore(make_entry, tmp_path, monkeypatch, prefix):
    from file_renamer.smoke import flac_fixture

    audio = flac_fixture(title="Synthetic crash-recovery audio")
    entry = make_entry("album/a.flac", audio)
    plan = build_plan([entry], [RuleSpec("insert", options={"text": prefix})])
    assert not plan.errors
    manager = TransactionManager(tmp_path / "data" / "last-rename.json")
    reserved = transactions._recovery_capacity_snapshot(_initial_snapshot(plan))
    limit = len(storage.serialize_json(reserved).encode("utf-8"))
    monkeypatch.setattr(storage, "MAX_JSON_BYTES", limit)
    actual_rename = transactions.rename_no_replace

    def crash_after_stage(source, target):
        actual_rename(source, target)
        raise SystemExit("Stopped after staging, before completion event")

    with monkeypatch.context() as patch:
        patch.setattr(transactions, "rename_no_replace", crash_after_stage)
        with pytest.raises(SystemExit):
            manager.execute(plan)
    replayed = TransactionManager(manager.journal).load()
    assert replayed["pending"] is not None
    assert len(storage.serialize_json(replayed).encode("utf-8")) <= limit
    restored = TransactionManager(manager.journal).restore()
    assert restored.success, restored.message
    assert Path(entry.path).read_bytes() == audio
    assert set(Path(entry.path).parent.iterdir()) == {Path(entry.path)}
    assert manager.load()["status"] == "rolled_back"
    assert manager.journal.stat().st_size <= limit


def _legacy_staged_flac(make_entry, tmp_path):
    from file_renamer.smoke import flac_fixture

    audio = flac_fixture(title="Legacy recovery fixture")
    entry = make_entry("album/a.flac", audio)
    plan = _plan(entry)
    manager = TransactionManager(tmp_path / "data" / "last-rename.json")
    data = _initial_snapshot(plan)
    storage.atomic_json(manager.journal, data)
    baseline = manager.journal.read_bytes()
    staged = str(Path(entry.path).with_name(".file-renamer-" + "1" * 32 + ".tmp"))
    # Version 2.2.8 wrote the same pending/current log records, but did not
    # reserve enough snapshot space for their replay before starting a batch.
    manager._move(data, 0, staged)
    return manager, entry, audio, baseline


@pytest.mark.parametrize("terminal_fits", [True, False])
def test_legacy_oversized_replay_recovers_with_bounded_snapshot(
    make_entry, tmp_path, monkeypatch, terminal_fits,
):
    manager, entry, audio, baseline = _legacy_staged_flac(make_entry, tmp_path)
    limit = len(baseline) + (16 if terminal_fits else 0)
    monkeypatch.setattr(storage, "MAX_JSON_BYTES", limit)
    with pytest.raises(ValueError, match="too large"):
        storage.serialize_json(manager.load())
    log_before = manager.journal.with_suffix(".log").read_bytes()
    result = TransactionManager(manager.journal).restore()
    assert result.success, result.message
    assert Path(entry.path).read_bytes() == audio
    assert set(Path(entry.path).parent.iterdir()) == {Path(entry.path)}
    assert manager.journal.stat().st_size <= limit
    assert manager.journal.with_suffix(".log").read_bytes().startswith(log_before)
    restored = TransactionManager(manager.journal).load()
    assert restored["status"] == "rolled_back" and restored["pending"] is None
    assert restored["records"][0]["current"] == entry.path
    if terminal_fits:
        assert storage.read_json(manager.journal)["status"] == "rolled_back"
    else:
        assert manager.journal.read_bytes() == baseline
        with pytest.raises(ValueError, match="too large"):
            storage.serialize_json(restored)
    assert not TransactionManager(manager.journal).restore().success


def test_legacy_oversized_replay_survives_crash_during_recovery(make_entry, tmp_path, monkeypatch):
    manager, entry, audio, baseline = _legacy_staged_flac(make_entry, tmp_path)
    monkeypatch.setattr(storage, "MAX_JSON_BYTES", len(baseline))
    actual_rename = transactions.rename_no_replace

    def crash_after_recovery_stage(source, target):
        actual_rename(source, target)
        raise SystemExit("Stopped during legacy recovery after move, before completion log")

    with monkeypatch.context() as patch:
        patch.setattr(transactions, "rename_no_replace", crash_after_recovery_stage)
        with pytest.raises(SystemExit):
            TransactionManager(manager.journal).restore()
    interrupted = TransactionManager(manager.journal).load()
    assert interrupted["status"] == "active" and interrupted["pending"] is not None
    assert manager.journal.read_bytes() == baseline
    result = TransactionManager(manager.journal).restore()
    assert result.success, result.message
    assert Path(entry.path).read_bytes() == audio
    assert set(Path(entry.path).parent.iterdir()) == {Path(entry.path)}
    assert TransactionManager(manager.journal).load()["status"] == "rolled_back"
    assert manager.journal.read_bytes() == baseline


def test_legacy_oversized_replay_persists_failed_recovery_status(make_entry, tmp_path, monkeypatch):
    manager, entry, audio, baseline = _legacy_staged_flac(make_entry, tmp_path)
    monkeypatch.setattr(storage, "MAX_JSON_BYTES", len(baseline))

    def fail_move(source, target):
        raise OSError("Simulated temporarily unavailable music folder")

    with monkeypatch.context() as patch:
        patch.setattr(transactions, "rename_no_replace", fail_move)
        result = TransactionManager(manager.journal).restore()
    assert not result.success and result.recovery_required
    assert TransactionManager(manager.journal).load()["status"] == "needs_recovery"
    assert manager.journal.read_bytes() == baseline
    result = TransactionManager(manager.journal).restore()
    assert result.success, result.message
    assert Path(entry.path).read_bytes() == audio
    assert TransactionManager(manager.journal).load()["status"] == "rolled_back"
