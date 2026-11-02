from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from .filename_policy import filename_error
from .filesystem import hidden_path, matches, name_error, path_key
from .models import FileEntry, PlannedFile, RenamePlan, RuleSpec
from .rules import apply_rule


def validate_plan(plan: RenamePlan) -> RenamePlan:
    sensitivity: dict[str, bool] = {}
    limits: dict[str, int] = {}
    destinations: dict[str, list[int]] = {}
    sources: dict[str, PlannedFile] = {}
    rows = list(plan.files)
    for i, item in enumerate(rows):
        if not item.entry.included:
            continue
        source, target = Path(item.entry.path), Path(item.destination)
        error = item.error
        try:
            if hidden_path(source):
                error = "Hidden files and folder contents are excluded"
        except OSError:
            error = "Source is unavailable; remove it and add it again"
        if not matches(source, item.entry.identity):
            error = "Source changed, is missing, or is a link; remove it and add it again"
        if source.parent != target.parent:
            error = "Files must remain in their current folder"
        error = error or name_error(target, limits)
        rows[i] = replace(item, error=error)
        source_key = path_key(source, sensitivity)
        if source_key in sources:
            rows[i] = replace(rows[i], error="Duplicate source file")
        sources[source_key] = rows[i]
        destinations.setdefault(path_key(target, sensitivity), []).append(i)
    for key, indices in destinations.items():
        for i in indices:
            item = rows[i]
            error = item.error
            if len(indices) > 1:
                error = "Two included files have the same destination"
            elif os.path.lexists(item.destination):
                occupant = sources.get(key)
                if occupant is None or not matches(item.destination, occupant.entry.identity):
                    error = "Destination already exists"
            rows[i] = replace(item, error=error)
    return RenamePlan(plan.revision, tuple(rows))


def build_plan(entries: list[FileEntry], rules: list[RuleSpec], revision: int = 0, snapshot=None) -> RenamePlan:
    from datetime import datetime

    from .compat_rules import Evaluation
    from .metadata import Metadata

    snapshot = snapshot or {}
    context = Evaluation(
        now=datetime.fromisoformat(snapshot["now"]) if snapshot.get("now") else datetime.now(),
        clipboard=snapshot.get("clipboard", ""),
    )
    context.metadata = Metadata(context.now, context.clipboard)
    context.files = tuple(entry.path for entry in entries)
    context.marked_files = tuple(entry.path for entry in entries if entry.included)
    context.application_path = snapshot.get("application_path", "")
    context.application_params = tuple(snapshot.get("application_params", ()))
    rows = []
    global_index = 0
    folder_indices: dict[str, int] = {}
    for file_index, entry in enumerate(entries):
        source = Path(entry.path)
        if not entry.included:
            rows.append(PlannedFile(entry, entry.path))
            continue
        name, error = source.name, ""
        folder = str(source.parent)
        folder_index = folder_indices.get(folder, 0)
        try:
            context.path, context.index = entry.path, global_index
            context.file_index = file_index
            for rule_no, rule in enumerate(rules):
                context.rule_index = rule_no
                index = folder_index if rule.options.get("per_folder", False) else global_index
                name = apply_rule(name, rule, index, context)
                if len(name) > 32768:
                    raise ValueError("Resulting name is too long")
            error = filename_error(name)
            if error:
                raise ValueError(error)
        except Exception as exc:
            name, error = source.name, str(exc)
        rows.append(PlannedFile(entry, str(source.parent / name), error))
        global_index += 1
        folder_indices[folder] = folder_index + 1
    for session in context.pascal.values():
        session.close()
    return validate_plan(RenamePlan(revision, tuple(rows)))
