"""Journaled two-phase, no-clobber rename and recovery."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable

from .filesystem import matches, path_key, rename_no_replace
from .models import FileIdentity, OperationResult, RenamePlan
from .planner import validate_plan
from .storage import atomic_json, read_json


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

    def _append(self, data: dict, event: dict) -> None:
        """Fsync a small event instead of rewriting the whole batch for every file."""
        sequence = data.get("sequence", 0) + 1
        payload = event | {"sequence": sequence, "transaction": data["transaction"]}
        path = self.journal.with_suffix(".log")
        with path.open("a+b") as handle:
            length = handle.tell()
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

    def _reconcile(self, data: dict) -> None:
        pending = data.get("pending")
        if not pending:
            return
        record = data["records"][pending["index"]]
        identity = FileIdentity(**record["identity"])
        at_from, at_to = matches(pending["from"], identity), matches(pending["to"], identity)
        if at_from == at_to:
            raise OSError(f"Cannot safely locate interrupted file: {pending['from']} → {pending['to']}")
        record["current"] = pending["to"] if at_to else pending["from"]
        data["pending"] = None
        self._append(data, {"index": pending["index"], "current": record["current"], "pending": None})

    def _move(self, data: dict, index: int, target: str) -> None:
        record = data["records"][index]
        source = record["current"]
        if not matches(source, FileIdentity(**record["identity"])):
            raise OSError(f"File changed or disappeared: {source}")
        data["pending"] = {"index": index, "from": source, "to": target}
        self._append(data, {"pending": data["pending"]})
        rename_no_replace(source, target)
        # Sync directory metadata before marking the operation complete on Linux.
        if os.name != "nt":
            directory = os.open(Path(source).parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        record["current"] = target
        data["pending"] = None
        self._append(data, {"index": index, "current": target, "pending": None})

    def _transfer(self, data: dict, destination_key: str, cancelled: Callable[[], bool], progress) -> None:
        self._reconcile(data)
        records = data["records"]
        moving = [i for i, row in enumerate(records) if row["current"] != row[destination_key]]
        for row in records:
            if not matches(row["current"], FileIdentity(**row["identity"])):
                raise OSError(f"File changed or disappeared: {row['current']}")
        occupied = {path_key(row["current"]): row for row in records}
        for row in records:
            target = row[destination_key]
            if os.path.lexists(target):
                owner = occupied.get(path_key(target))
                if owner is None or not matches(target, FileIdentity(**owner["identity"])):
                    raise FileExistsError(f"Destination already exists: {target}")
        # Stage all changing entries so swaps and longer cycles can be resolved.
        total = len(moving) * 2
        done = 0
        for index in moving:
            if cancelled():
                raise InterruptedError("Rename cancelled")
            row = records[index]
            temporary = str(Path(row["original"]).with_name(f".file-renamer-{uuid.uuid4().hex}.tmp"))
            self._move(data, index, temporary)
            done += 1
            progress(done, total)
        for index in moving:
            if cancelled():
                raise InterruptedError("Rename cancelled")
            self._move(data, index, records[index][destination_key])
            done += 1
            progress(done, total)

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
        self._save(data)
        # A new transaction ID makes old events harmless if interruption occurs here.
        with self.journal.with_suffix(".log").open("wb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        try:
            self._transfer(data, "target", cancelled, progress)
            data["status"] = "committed"
            self._save(data)
            return OperationResult(True, f"Renamed {len(data['records'])} files.", self._paths(data))
        except Exception as exc:
            # Read the durable state: a move may have completed before a journal update failed.
            try:
                data = self.load()
                self._transfer(data, "original", lambda: False, lambda *_: None)
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
            data["status"] = "active"
            self._save(data)
            self._transfer(data, "original", lambda: False, progress)
            data["status"] = "undone" if was_committed else "rolled_back"
            self._save(data)
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
            self._save(data)
        except Exception:
            pass
        paths = self._paths(data)
        detail = "\n".join(f"{source} → {current}" for source, current in paths if source != current)
        if data.get("pending"):
            pending = data["pending"]
            detail += f"\nInterrupted move (location needs verification): {pending['from']} → {pending['to']}"
        return OperationResult(False, f"{message}\nJournal: {self.journal}\n{detail}", paths, True)
