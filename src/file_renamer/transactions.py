"""Journaled two-phase, no-clobber rename and recovery."""
from __future__ import annotations

import json
import os
import re
import stat
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable

from .filesystem import matches, path_key, regular_identity, rename_no_replace
from .models import FileIdentity, OperationResult, RenamePlan
from .planner import validate_plan
from .storage import atomic_json, read_json, serialize_json
from .storage import sync_directory as _sync_directory

TEMPORARY_MARKER = ".file-renamer-"
_TEMPORARY_NAME = re.compile(r"\.file-renamer-[0-9a-f]{12,32}(\.|$)")


def temporary_name(original: str | Path, token: str, limit: int = 255) -> str:
    """A visible, recognizable staging name that keeps the stem and extension.

    Earlier releases staged under ".file-renamer-<id>.tmp", which hid the file
    and discarded its name if a batch could not finish.
    """
    original = Path(original)
    stem, suffix = original.stem.lstrip(".") or "file", original.suffix
    tail = f"{TEMPORARY_MARKER}{token}{suffix}"
    if len(os.fsencode(tail)) > limit - 4:
        tail = f"{TEMPORARY_MARKER}{token}"

    def length(name: str) -> int:
        return max(len(os.fsencode(name)), len(name.encode("utf-16-le", "surrogatepass")) // 2)

    while len(stem) > 1 and length(stem + tail) > limit:
        stem = stem[:-1]
    return stem + tail


def is_temporary_name(name: str) -> bool:
    return bool(_TEMPORARY_NAME.search(name))


def _name_limit(directory: Path) -> int:
    if os.name != "nt":
        try:
            limit = os.pathconf(directory, "PC_NAME_MAX")
            if limit > 0:
                return min(limit, 255)
        except (OSError, ValueError):
            pass
    return 255


def _recovery_capacity_snapshot(data: dict) -> dict:
    """Bound checkpoint size even after log replay or an interrupted move."""
    def path_size(value: str) -> int:
        return len(json.dumps(value, ensure_ascii=True))

    records = []
    longest_paths = []
    for row in data["records"]:
        # Untruncated, so it bounds every staging name the batch can use.
        original = Path(row["original"])
        temporary = str(original.with_name(original.name + TEMPORARY_MARKER + "0" * 32 + original.suffix))
        longest = max((row["original"], row["target"], temporary), key=path_size)
        records.append(row | {"current": longest})
        longest_paths.append(longest)
    longest = max(longest_paths, key=path_size)
    return data | {
        "status": "needs_recovery",
        "sequence": 10 ** 20 - 1,
        "records": records,
        "pending": {"index": len(records) - 1, "from": longest, "to": longest},
    }


class TransactionManager:
    def __init__(self, journal: Path):
        self.journal = journal

    def load(self) -> dict | None:
        if not self.journal.exists():
            return None
        data = read_json(self.journal)
        log = self.journal.with_suffix(".log")
        if log.exists():
            with log.open("rb") as handle:
                for line in handle:
                    if not line.endswith(b"\n"):
                        break  # A torn final append was never allowed to perform its move.
                    event = json.loads(line)
                    if event.get("transaction") != data.get("transaction"):
                        continue
                    if event["sequence"] <= data.get("sequence", 0):
                        continue
                    if event["sequence"] != data.get("sequence", 0) + 1:
                        raise ValueError("Recovery journal contains a gap")
                    data["sequence"] = event["sequence"]
                    if "current" in event:
                        data["records"][event["index"]]["current"] = event["current"]
                    data["pending"] = event["pending"]
                    if "status" in event:
                        data["status"] = event["status"]
        if data.get("version") != 1 or data.get("status") not in {
            "active", "committed", "needs_recovery", "rolled_back", "undone"
        } or not isinstance(data.get("records"), list):
            raise ValueError(f"Invalid recovery journal: {self.journal}")
        for record in data["records"]:
            identity = FileIdentity(**record["identity"])
            if not all(type(value) is int for value in asdict(identity).values()):
                raise ValueError("Invalid journal identity")
            paths = [Path(record[key]) for key in ("original", "target", "current")]
            if not all(path.is_absolute() for path in paths) or len({str(path.parent) for path in paths}) != 1:
                raise ValueError("Journal paths must share an absolute parent")
        pending = data.get("pending")
        if pending:
            record = data["records"][pending["index"]]
            if pending["from"] != record["current"] or Path(pending["to"]).parent != Path(record["original"]).parent:
                raise ValueError("Invalid pending journal operation")
        return data

    def _save(self, data: dict) -> None:
        atomic_json(self.journal, data)

    def _sync_journal_directories(self) -> None:
        # Hierarchy creation is synced by ensure_directory before a snapshot
        # is written. Only this directory's snapshot/log names changed here.
        _sync_directory(self.journal.absolute().parent)

    def _checkpoint_recovery(self, data: dict) -> None:
        """Persist a replayed recovery state without requiring a larger snapshot.

        All record/current/pending changes already exist in the snapshot and
        move log. Only the status transition is new here. Legacy batches may
        replay past the reader's snapshot limit, so keep that durable pair and
        append a small status event rather than replacing it with unreadable
        JSON. A fitting snapshot can still compact the replay normally.
        """
        self._append(data, {"status": data["status"], "pending": data["pending"]})
        self._sync_journal_directories()
        try:
            serialize_json(data)
        except ValueError:
            return
        self._save(data)

    def _open_log(self, truncate: bool = False):
        """Open the move log without following a link or touching a shared file."""
        path = self.journal.with_suffix(".log")
        if path.is_symlink():
            raise OSError(f"Recovery log must not be a link: {path}")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                raise OSError(f"Recovery log must be a private regular file: {path}")
            if truncate:
                os.ftruncate(descriptor, 0)
            return os.fdopen(descriptor, "r+b")
        except BaseException:
            os.close(descriptor)
            raise

    def _append(self, data: dict, event: dict) -> None:
        """Fsync a small event instead of rewriting the whole batch for every file."""
        sequence = data.get("sequence", 0) + 1
        payload = event | {"sequence": sequence, "transaction": data["transaction"]}
        with self._open_log() as handle:
            length = handle.seek(0, os.SEEK_END)
            if length:
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) != b"\n":
                    handle.seek(0)
                    content = handle.read()
                    handle.truncate(content.rfind(b"\n") + 1)
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        data["sequence"] = sequence

    @staticmethod
    def _holds(path: str, record: dict) -> bool:
        """Whether path holds this record's file."""
        identity = FileIdentity(**record["identity"])
        if matches(path, identity):
            return True
        # Only this app creates its unique staging names, so the journal entry
        # is the authority there even where device or inode numbers changed.
        if path in (record["original"], record["target"]) or not is_temporary_name(Path(path).name):
            return False
        try:
            return regular_identity(path).size == identity.size
        except (OSError, ValueError):
            return False

    def _reconcile(self, data: dict) -> None:
        pending = data.get("pending")
        if not pending:
            return
        record = data["records"][pending["index"]]
        at_from, at_to = self._holds(pending["from"], record), self._holds(pending["to"], record)
        if at_from == at_to:
            raise OSError(f"Cannot safely locate interrupted file: {pending['from']} \u2192 {pending['to']}")
        record["current"] = pending["to"] if at_to else pending["from"]
        data["pending"] = None
        self._append(data, {"index": pending["index"], "current": record["current"], "pending": None})

    def _move(self, data: dict, index: int, target: str) -> None:
        record = data["records"][index]
        source = record["current"]
        if not self._holds(source, record):
            raise OSError(f"File changed or disappeared: {source}")
        data["pending"] = {"index": index, "from": source, "to": target}
        self._append(data, {"pending": data["pending"]})
        rename_no_replace(source, target)
        # Sync directory metadata before marking the operation complete on Linux.
        _sync_directory(Path(source).parent)
        record["current"] = target
        data["pending"] = None
        self._append(data, {"index": index, "current": target, "pending": None})

    @staticmethod
    def _preflight_directories(data: dict) -> None:
        # Detect filesystems that reject directory syncing before any file
        # moves. Every later move still syncs again.
        for parent in dict.fromkeys(Path(row["original"]).parent for row in data["records"]):
            _sync_directory(parent)

    def _transfer(self, data: dict, destination_key: str, cancelled: Callable[[], bool], progress,
                  best_effort: bool = False) -> None:
        """Move every record to its destination name.

        A file moves straight to its destination whenever that name is free.
        Only swaps, longer cycles and case-only changes pass through a staging
        name, one file per cycle. With best_effort (restoring originals), a
        file that cannot be moved is reported after every other file has been
        restored instead of stopping the whole batch.
        """
        self._reconcile(data)
        records = data["records"]
        sensitivity: dict[str, bool] = {}
        failures: list[str] = []

        def key(path: str) -> str:
            return path_key(path, sensitivity)

        def failed(index: int, error: Exception) -> None:
            if not best_effort:
                raise error
            failures.append(str(error))
            pending.discard(index)

        pending = {i for i, row in enumerate(records) if row["current"] != row[destination_key]}
        for index, row in enumerate(records):
            if not self._holds(row["current"], row):
                error = OSError(f"File changed or disappeared: {row['current']}")
                if not best_effort:
                    raise error
                if index in pending:
                    failed(index, error)
        occupied = {key(row["current"]): index for index, row in enumerate(records)}
        for index in sorted(pending):
            target = records[index][destination_key]
            if os.path.lexists(target):
                owner = occupied.get(key(target))
                if owner is None or not self._holds(target, records[owner]):
                    failed(index, FileExistsError(f"Destination already exists: {target}"))

        total, done = len(pending), 0

        def relocate(index: int, target: str) -> bool:
            source = records[index]["current"]
            try:
                self._move(data, index, target)
            except OSError as exc:
                if not best_effort:
                    raise
                self._reconcile(data)  # The move was logged as pending; settle where the file is.
                failed(index, exc)
                return False
            if occupied.get(key(source)) == index:
                del occupied[key(source)]
            occupied[key(target)] = index
            return True

        def stage(index: int) -> bool:
            original = Path(records[index]["original"])
            name = temporary_name(original, uuid.uuid4().hex[:16], _name_limit(original.parent))
            return relocate(index, str(original.with_name(name)))

        for first in sorted(pending):
            if first not in pending:
                continue
            chain, seen, index = [], set(), first
            while True:
                chain.append(index)
                seen.add(index)
                blocker = occupied.get(key(records[index][destination_key]))
                if blocker is None or blocker not in pending:
                    break
                if blocker in seen:
                    if cancelled():
                        raise InterruptedError("Rename cancelled")
                    stage(blocker)  # A swap, cycle or case-only change: free one name.
                    break
                index = blocker
            for index in reversed(chain):
                if index not in pending:
                    continue
                if cancelled():
                    raise InterruptedError("Rename cancelled")
                target = records[index][destination_key]
                try:
                    moved = relocate(index, target)
                except FileExistsError:
                    # A case-insensitive folder that reported itself as case-sensitive.
                    current = records[index]["current"]
                    if not (os.path.lexists(target) and os.path.samefile(current, target)):
                        raise
                    self._reconcile(data)
                    moved = stage(index) and relocate(index, target)
                if moved:
                    pending.discard(index)
                    done += 1
                    progress(done, total)
        if failures:
            more = f" (and {len(failures) - 1} more)" if len(failures) > 1 else ""
            raise OSError(f"{failures[0]}{more}")

    def execute(self, plan: RenamePlan, cancelled=lambda: False, progress=lambda *_: None) -> OperationResult:
        previous = self.load()
        if previous and previous["status"] in {"active", "needs_recovery"}:
            return OperationResult(False, "Recover the interrupted operation before starting another.",
                                   recovery_required=True)
        checked = validate_plan(plan)
        if checked.errors:
            return OperationResult(False, "Nothing renamed. " + checked.errors[0].error)
        if not checked.changes:
            return OperationResult(False, "No filenames need to change.")
        data = {"version": 1, "transaction": uuid.uuid4().hex, "sequence": 0,
                "status": "active", "pending": None, "records": [
            {"original": row.entry.path, "target": row.destination, "current": row.entry.path,
             "identity": asdict(row.entry.identity)} for row in checked.changes
        ]}
        try:
            # Replayed current paths and pending moves can be much larger than
            # the initial snapshot. Reserve their maximum before replacing Undo.
            serialize_json(_recovery_capacity_snapshot(data))
        except ValueError as exc:
            return OperationResult(False, f"Nothing renamed. Recovery journal could not be prepared: {exc}")
        try:
            self._preflight_directories(data)
        except OSError as exc:
            return OperationResult(False, f"Nothing renamed. The file folder could not be synced: {exc}")
        try:
            self._save(data)
            # A new transaction ID makes old events harmless if interruption occurs here.
            with self._open_log(truncate=True) as handle:
                handle.flush()
                os.fsync(handle.fileno())
            # Fsyncing the log's contents does not persist a newly created name.
            # Its directory entry must be durable before the first source move.
            # Newly created directory components were synced before _save.
            self._sync_journal_directories()
        except Exception as exc:
            # No source has moved. Checkpoint the fully replayed prior history,
            # since resetting the log may already have removed its old events.
            checkpoint = previous if previous is not None else data | {"status": "rolled_back"}
            try:
                self._save(checkpoint)
            except Exception as checkpoint_error:
                return OperationResult(
                    False,
                    f"Nothing renamed. Recovery journal preparation failed: {exc}\n"
                    f"The recovery journal could not be restored: {checkpoint_error}\nJournal: {self.journal}",
                    recovery_required=True,
                )
            return OperationResult(False, f"Nothing renamed. Recovery journal preparation failed: {exc}")
        try:
            self._transfer(data, "target", cancelled, progress)
            data["status"] = "committed"
            self._save(data)
            return OperationResult(True, f"Renamed {len(data['records'])} files.", self._paths(data))
        except Exception as exc:
            # Read the durable state: a move may have completed before a journal update failed.
            try:
                data = self.load()
                self._transfer(data, "original", lambda: False, lambda *_: None, best_effort=True)
                data["status"] = "rolled_back"
                self._save(data)
                return OperationResult(False, f"{exc}\nAll filenames were restored.", self._paths(data))
            except Exception as recovery_error:
                return self._failure(data, f"{exc}\nRecovery needed: {recovery_error}")

    def restore(self, progress=lambda *_: None) -> OperationResult:
        data = self.load()
        if not data or data["status"] in {"undone", "rolled_back"}:
            return OperationResult(False, "There is no rename to undo.")
        was_committed = data["status"] == "committed"
        before = [row["current"] for row in data["records"]]
        try:
            self._preflight_directories(data)
            data["status"] = "active"
            self._checkpoint_recovery(data)
            self._transfer(data, "original", lambda: False, progress, best_effort=True)
            data["status"] = "undone" if was_committed else "rolled_back"
            self._checkpoint_recovery(data)
            paths = tuple((source, row["original"]) for source, row in zip(before, data["records"]))
            return OperationResult(True, "Original filenames restored.", paths)
        except Exception as exc:
            result = self._failure(data, f"Could not restore every filename: {exc}")
            return replace(result, paths=tuple((source, current) for source, (_, current) in zip(before, result.paths)))

    @staticmethod
    def _paths(data: dict) -> tuple[tuple[str, str], ...]:
        return tuple((row["original"], row["current"]) for row in data["records"])

    def _failure(self, data: dict, message: str) -> OperationResult:
        try:
            # Do not overwrite an unresolved pending operation with an in-memory approximation.
            data = self.load() or data
            data["status"] = "needs_recovery"
            self._checkpoint_recovery(data)
        except Exception:
            pass
        paths = self._paths(data)
        detail = "\n".join(f"{source} → {current}" for source, current in paths if source != current)
        if data.get("pending"):
            pending = data["pending"]
            detail += f"\nInterrupted move (location needs verification): {pending['from']} → {pending['to']}"
        return OperationResult(False, f"{message}\nJournal: {self.journal}\n{detail}", paths, True)
