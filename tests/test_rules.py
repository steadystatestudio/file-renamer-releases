from dataclasses import replace

import pytest

from file_renamer.models import RuleSpec
from file_renamer.planner import build_plan
from file_renamer.rules import apply_rule, validate_rule


@pytest.mark.parametrize("name,rule,expected", [
    ("PHOTO.JPG", RuleSpec("case", options={"mode": "lower"}), "photo.JPG"),
    ("PHOTO.JPG", RuleSpec("case", "name", options={"mode": "lower"}), "photo.jpg"),
    ("PHOTO.JPG", RuleSpec("case", "extension", options={"mode": "lower"}), "PHOTO.jpg"),
    ("archive.tar.gz", RuleSpec("insert", options={"text": "new_"}), "new_archive.tar.gz"),
    (".config", RuleSpec("insert", options={"text": "new_"}), "new_.config"),
    ("abc.txt", RuleSpec("delete", options={"start": 1, "count": 100}), "a.txt"),
    ("AA-a.txt", RuleSpec("remove", options={"text": "a", "case_sensitive": False}), "-.txt"),
    ("foo_foo.txt", RuleSpec("replace", options={"find": "foo", "replacement": r"\1", "all": False}),
     r"\1_foo.txt"),
    ("image.JPG", RuleSpec("extension", options={"text": "png"}), "image.png"),
    ("image.JPG", RuleSpec("extension", options={"text": ""}), "image"),
    ("image.jpg", RuleSpec("number", options={"start": 9, "width": 4}), "0009_image.jpg"),
    ("v00042_1.txt", RuleSpec("padding", options={"width": 3}), "v042_001.txt"),
    ("  hello__world--.txt", RuleSpec("cleanup", options={"separator": "-"}), "hello-world.txt"),
    ("猫_42.jpg", RuleSpec("regex", options={"pattern": r"^(.*)_(\d+)$", "replacement": r"\g<2>_\g<1>"}),
     "42_猫.jpg"),
    ("abc.txt", RuleSpec("case", enabled=False), "abc.txt"),
])
def test_transformations(name, rule, expected):
    assert apply_rule(name, rule, 0) == expected


def test_order_numbering_and_exclusion(make_entry):
    a, b, c = [make_entry(name) for name in ("one/a.txt", "one/b.txt", "two/c.txt")]
    rules = [RuleSpec("number"), RuleSpec("case", options={"mode": "upper"})]
    plan = build_plan([c, replace(a, included=False), b], rules)
    assert plan.files[0].destination.endswith("001_C.txt")
    assert plan.files[1].destination == a.path
    assert plan.files[2].destination.endswith("002_B.txt")
    plan = build_plan([a, b, c], [RuleSpec("number", options={"per_folder": True})])
    assert plan.files[2].destination.endswith("001_c.txt")


def test_invalid_regex_and_path_injection(make_entry):
    entry = make_entry("a.txt")
    assert build_plan([entry], [RuleSpec("regex", options={"pattern": "["})]).errors
    assert build_plan([entry], [RuleSpec("insert", options={"text": "../"})]).errors


def test_rule_validation():
    with pytest.raises(ValueError):
        validate_rule(RuleSpec("number", options={"width": 999999}))
    with pytest.raises(ValueError):
        validate_rule(RuleSpec("unknown"))


def test_rule_options_are_immutable():
    options = {"text": "original"}
    rule = RuleSpec("insert", options=options)
    options["text"] = "changed"
    assert rule.options["text"] == "original"
    with pytest.raises(TypeError):
        rule.options["text"] = "changed"
