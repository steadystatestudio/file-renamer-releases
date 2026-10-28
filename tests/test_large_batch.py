from pathlib import Path

from file_renamer.filesystem import scan_paths
from file_renamer.models import RuleSpec
from file_renamer.planner import build_plan


def test_ten_thousand_file_preview(tmp_path):
    for index in range(10000):
        (tmp_path / f"photo_{index:05}.jpg").touch()
    entries, errors = scan_paths([str(tmp_path)], False)
    assert not errors and len(entries) == 10000
    plan = build_plan(entries, [RuleSpec("number", options={"width": 5})])
    assert not plan.errors
    assert len(plan.changes) == 10000
    assert Path(plan.files[0].destination).name == "00001_photo_00000.jpg"
    assert Path(plan.files[-1].destination).name == "10000_photo_09999.jpg"
    assert not Path(plan.files[0].destination).exists()
