from datetime import datetime

import pytest

from file_renamer.compat_rules import Evaluation
from file_renamer.models import RuleSpec
from file_renamer.rules import apply_rule


@pytest.mark.parametrize(
    "kind,name,options,expected",
    [
        ("replace", "a b.txt", {"find": "a*|*b", "replacement": "x"}, "x x.txt"),
        ("strip", "abc.txt", {"characters": "a", "use_characters": False}, "abc.txt"),
        ("date", "12-25.txt", {"find_formats": "mm-dd", "format": "yyyy-mm-dd"}, "2026-12-25.txt"),
        ("date", "2024-01-31.txt", {"months": 1, "adjust_time": False, "format": "yyyy-mm-dd"}, "2024-01-31.txt"),
    ],
)
def test_optional_settings_and_partial_dates(kind, name, options, expected):
    context = Evaluation(now=datetime(2026, 10, 2))
    rule = RuleSpec(kind, options=options, behavior="renamer")
    assert apply_rule(name, rule, 0, context=context) == expected
