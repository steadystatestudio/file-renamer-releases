from __future__ import annotations

import json
import os
import tempfile
import tomllib
from dataclasses import asdict
from pathlib import Path

import tomli_w

from .models import RuleSpec
from .registry import defaults_for
from .rules import validate_rule


def atomic_json(path: Path, data: dict) -> None:
    atomic_text(path, json.dumps(data, ensure_ascii=True, indent=2))


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".renamer-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> dict:
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Data file is too large")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def preset_data(name: str, rules: list[RuleSpec]) -> dict:
    return {"version": 2, "name": name, "rules": [asdict(rule) for rule in rules]}


def parse_preset(data: dict) -> tuple[str, list[RuleSpec]]:
    if not isinstance(data, dict) or set(data) - {"version", "name", "rules"}:
        raise ValueError("Invalid preset fields")
    if data.get("version") not in {1, 2}:
        raise ValueError("Unsupported preset version")
    name, raw_rules = data.get("name"), data.get("rules")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("Preset name must contain 1–120 characters")
    if not isinstance(raw_rules, list) or len(raw_rules) > 100:
        raise ValueError("Preset must contain at most 100 rules")
    rules = []
    for raw in raw_rules:
        if not isinstance(raw, dict) or set(raw) - {"kind", "target", "enabled", "options", "behavior"}:
            raise ValueError("Invalid rule")
        try:
            if data["version"] == 1:
                raw = dict(raw, behavior="legacy")
            rule = RuleSpec(**raw)
        except TypeError as exc:
            raise ValueError("Rule is missing its type or contains invalid fields") from exc
        if type(rule.enabled) is not bool or not isinstance(rule.options, dict):
            raise ValueError("Invalid rule values")
        validate_rule(rule)
        rules.append(rule)
    return name.strip(), rules


class PresetStore:
    def __init__(self, path: Path):
        self.path = path
        self.presets: dict[str, list[RuleSpec]] = {}
        if path.exists():
            data = read_json(path)
            if data.get("version") not in {1, 2} or not isinstance(data.get("presets"), list):
                raise ValueError("Invalid preset library")
            for preset in data["presets"]:
                name, rules = parse_preset(preset)
                self.presets[name] = rules

    def save(self, name: str, rules: list[RuleSpec]) -> None:
        name, rules = parse_preset(preset_data(name, rules))
        updated = self.presets | {name: rules}
        self._write(updated)

    def delete(self, name: str) -> None:
        self._write({key: value for key, value in self.presets.items() if key != name})

    def _write(self, presets: dict[str, list[RuleSpec]]) -> None:
        atomic_json(self.path, {"version": 2, "presets": [preset_data(k, v) for k, v in presets.items()]})
        self.presets = presets


def backup_preset(path: Path, name: str, rules: list[RuleSpec]) -> None:
    if path.suffix.lower() not in {".toml", ".json"}:
        raise ValueError("Choose a .toml or .json filename")
    data = preset_data(name, rules)
    parse_preset(data)
    if path.suffix.lower() == ".json":
        atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for raw, rule in zip(data["rules"], rules):
            raw["options"] = defaults_for(rule) | rule.options
        header = ("# File Renamer rule preset. Edit with any UTF-8 text editor.\n"
                  "# Rules run from top to bottom; enabled = false skips a rule.\n"
                  "# target: stem = name without extension, extension = extension only, name = full filename.\n"
                  "# Back up again to regenerate these comments.\n\n")
        atomic_text(path, header + tomli_w.dumps(data))


def restore_preset(path: Path) -> tuple[str, list[RuleSpec]]:
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Data file is too large")
    if path.suffix.lower() == ".json":
        data = read_json(path)
    else:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    return parse_preset(data)
