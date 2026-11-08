import json

import pytest

from file_renamer import storage
from file_renamer.models import RuleSpec
from file_renamer.storage import PresetStore, parse_preset, preset_data


def test_presets_roundtrip(tmp_path):
    path = tmp_path / "presets.json"
    store = PresetStore(path)
    rules = [RuleSpec("insert", options={"text": "猫_"}), RuleSpec("case", enabled=False)]
    store.save("Photos", rules)
    assert PresetStore(path).presets["Photos"] == rules
    assert parse_preset(preset_data("Photos", rules)) == ("Photos", rules)
    store.delete("Photos")
    assert not PresetStore(path).presets


@pytest.mark.parametrize("data", [
    {"version": 3, "name": "x", "rules": []},
    {"version": 1, "name": "", "rules": []},
    {"version": 1, "name": "x", "rules": [{"kind": "script"}]},
    {"version": 1, "name": "x", "rules": [{"kind": "number", "options": {"width": "3"}}]},
])
def test_invalid_preset(data):
    with pytest.raises(ValueError):
        parse_preset(data)


def test_oversized_atomic_json_preserves_previous_file_and_creates_no_temporary(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    storage.atomic_json(path, {"version": 1})
    previous = path.read_bytes()
    monkeypatch.setattr(storage, "MAX_JSON_BYTES", len(previous))
    with pytest.raises(ValueError, match="too large"):
        storage.atomic_json(path, {"version": 1, "value": "more than the previous file"})
    assert path.read_bytes() == previous
    assert storage.read_json(path) == {"version": 1}
    assert set(tmp_path.iterdir()) == {path}
    fresh_path = tmp_path / "not-created" / "settings.json"
    with pytest.raises(ValueError, match="too large"):
        storage.atomic_json(fresh_path, {"value": "more than the previous file"})
    assert not fresh_path.parent.exists()


def test_json_size_limit_uses_serialized_non_ascii_bytes(tmp_path, monkeypatch):
    data = {"title": "猫🌼"}
    expected = json.dumps(data, ensure_ascii=True, indent=2).encode("utf-8")
    # Escaped Unicode contributes its serialized size, not just two characters.
    assert len(expected) > len(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    path = tmp_path / "unicode.json"
    monkeypatch.setattr(storage, "MAX_JSON_BYTES", len(expected))
    storage.atomic_json(path, data)
    assert path.read_bytes() == expected
    assert storage.read_json(path) == data
    monkeypatch.setattr(storage, "MAX_JSON_BYTES", len(expected) - 1)
    with pytest.raises(ValueError, match="too large"):
        storage.serialize_json(data)
    with pytest.raises(ValueError, match="too large"):
        storage.read_json(path)


def test_new_directory_hierarchy_sync_stops_at_first_existing_parent(tmp_path, monkeypatch):
    path = tmp_path / "new-organization" / "new-app" / "data"
    synced = []

    def sync(directory):
        assert directory.is_dir()
        synced.append(directory)

    monkeypatch.setattr(storage, "sync_directory", sync)
    storage.ensure_directory(path)
    assert synced == [path, path.parent, path.parent.parent, tmp_path]
    synced.clear()
    storage.ensure_directory(path)
    assert synced == []
    with pytest.raises(FileExistsError):
        storage.ensure_directory(path, exist_ok=False)


def test_new_hierarchy_sync_failure_prevents_recovery_snapshot_write(tmp_path, monkeypatch):
    path = tmp_path / "new-data" / "settings.json"

    def reject_parent(directory):
        if directory == tmp_path:
            raise PermissionError("New directory entry could not be made durable")

    monkeypatch.setattr(storage, "sync_directory", reject_parent)
    with pytest.raises(PermissionError, match="durable"):
        storage.atomic_json(path, {"version": 1})
    assert not path.exists()
    assert not path.parent.exists()


def test_failed_new_hierarchy_is_anchored_again_before_retry(tmp_path, monkeypatch):
    directory = tmp_path / "new-organization" / "new-app" / "data"
    attempts = []

    def fail_once(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise OSError("Simulated first directory-sync failure")

    monkeypatch.setattr(storage, "sync_directory", fail_once)
    with pytest.raises(OSError, match="first"):
        storage.ensure_directory(directory)
    assert not (tmp_path / "new-organization").exists()
    storage.ensure_directory(directory)
    assert attempts[1:] == [directory, directory.parent, directory.parent.parent, tmp_path]
