from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class FrozenOptions(dict):
    """JSON-compatible immutable mapping of scalar rule options."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("Rule options are immutable; construct a new RuleSpec")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int


@dataclass(frozen=True)
class FileEntry:
    path: str
    identity: FileIdentity
    included: bool = True


@dataclass(frozen=True)
class RuleSpec:
    kind: str
    target: str = "stem"
    enabled: bool = True
    # Copy and freeze the input so GUI edits cannot alter an in-flight request.
    options: dict[str, Any] = field(default_factory=dict)
    behavior: str = "legacy"

    def __post_init__(self):
        if not isinstance(self.options, dict):
            raise ValueError("Rule options must be an object")
        object.__setattr__(self, "options", FrozenOptions(self.options))


@dataclass(frozen=True)
class PlannedFile:
    entry: FileEntry
    destination: str
    error: str = ""

    @property
    def changed(self) -> bool:
        return self.entry.included and self.entry.path != self.destination and not self.error


@dataclass(frozen=True)
class RenamePlan:
    revision: int
    files: tuple[PlannedFile, ...]

    @property
    def changes(self) -> tuple[PlannedFile, ...]:
        return tuple(item for item in self.files if item.changed)

    @property
    def errors(self) -> tuple[PlannedFile, ...]:
        return tuple(item for item in self.files if item.entry.included and item.error)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RenamePlan:
        return cls(data["revision"], tuple(
            PlannedFile(entry_from_dict(row["entry"]), row["destination"], row["error"])
            for row in data["files"]
        ))


@dataclass(frozen=True)
class OperationResult:
    success: bool
    message: str
    paths: tuple[tuple[str, str], ...] = ()
    recovery_required: bool = False


def entry_from_dict(data: dict) -> FileEntry:
    return FileEntry(data["path"], FileIdentity(**data["identity"]), data.get("included", True))
