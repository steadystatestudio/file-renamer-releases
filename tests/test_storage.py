import pytest

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
