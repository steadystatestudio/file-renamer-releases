import pytest

from file_renamer.models import RuleSpec
from file_renamer.rules import apply_rule
from file_renamer.storage import parse_preset, preset_data


@pytest.mark.parametrize("behavior", ["renamer", "legacy"])
@pytest.mark.parametrize("name,expected", [
    ("It's.txt", "It's.txt"),
    ("IT'S A TEST.JPG", "It's A Test.JPG"),
    ("don't stop.txt", "Don't Stop.txt"),
    ("they’re bill’s notes.txt", "They’re Bill’s Notes.txt"),
    ("rock'n'roll.txt", "Rock'n'roll.txt"),
    ("'HELLO' ‘WORLD’.txt", "'Hello' ‘World’.txt"),
    ("one-two.three.txt", "One-Two.Three.txt"),
    ("l'été d’aujourd’hui.txt", "L'été D’aujourd’hui.txt"),
])
def test_title_case_preserves_apostrophes_in_words(behavior, name, expected):
    rule = RuleSpec("case", behavior=behavior, options={"mode": "title"})
    _, restored = parse_preset(preset_data("Case", [rule]))
    assert apply_rule(name, restored[0], 0) == expected


@pytest.mark.parametrize("options,expected", [
    ({"mode": "title", "preserve": True}, "IT's IPad's BOOK.TXT"),
    ({"mode": "title", "force_fragments": True, "fragments": "iPad", "extension_case": "lower"},
     "It's iPad's Book.txt"),
    ({"mode": "first"}, "It's ipad's book.TXT"),
    ({"mode": "sentence"}, "It's ipad's book.TXT"),
    ({"mode": "upper"}, "IT'S IPAD'S BOOK.TXT"),
    ({"mode": "lower"}, "it's ipad's book.TXT"),
])
def test_other_case_options_keep_their_meaning(options, expected):
    assert apply_rule("iT's iPad's BOOK.TXT", RuleSpec("case", behavior="renamer", options=options), 0) == expected


def test_existing_digit_and_underscore_boundaries_are_preserved():
    assert apply_rule("a_b2c.txt", RuleSpec("case", options={"mode": "title"}), 0) == "A_B2C.txt"
    assert apply_rule("a_b2c.txt", RuleSpec("case", behavior="renamer", options={"mode": "title"}), 0) == "A_b2c.txt"
