from datetime import datetime

import pytest

from file_renamer.compat_rules import Evaluation
from file_renamer.metadata import CATALOG, Metadata, tool_path, torrent_data
from file_renamer.models import RuleSpec
from file_renamer.pascal import PascalSession
from file_renamer.registry import REGISTRY
from file_renamer.rules import apply_rule, validate_rule
from file_renamer.storage import parse_preset, preset_data


def rename(kind, name, **options):
    context = Evaluation()
    try:
        return apply_rule(name, RuleSpec(kind, options=options, behavior="renamer"), 0, context=context)
    finally:
        for session in context.pascal.values():
            session.close()


@pytest.mark.parametrize(
    "kind,name,options,expected",
    [
        ("insert", "abc.txt", {"text": "X", "position": "index", "index": 2}, "aXbc.txt"),
        ("insert", "abc.txt", {"text": "X", "position": "after", "match": "b"}, "abXc.txt"),
        ("insert", "abc.txt", {"text": "X", "position": "suffix", "skip_extension": False}, "abc.txtX"),
        ("delete", "abc.txt", {"start": 2, "count": 1}, "ac.txt"),
        ("delete", "abc.txt", {"start": 1, "count": 2, "from_right": True}, "a.txt"),
        (
            "delete",
            "a[x]b.txt",
            {
                "from_mode": "delimiter",
                "delimiter": "[",
                "until_mode": "delimiter",
                "end_delimiter": "]",
                "keep_delimiters": True,
            },
            "a[]b.txt",
        ),
        ("remove", "AbAB.txt", {"text": "ab", "occurrence": "last"}, "Ab.txt"),
        ("replace", "a b a.txt", {"find": "a", "replacement": "x", "occurrence": "first"}, "x b a.txt"),
        ("replace", "a ab.txt", {"find": "a", "replacement": "x", "whole_words": True}, "x ab.txt"),
        ("replace", "a b.txt", {"find": "a*|*b", "replacement": "x*|*y"}, "x y.txt"),
        ("rearrange", "a_b_c.txt", {"delimiter": "_", "template": "$-1-$1-$0"}, "c-a-a_b_c.txt"),
        (
            "rearrange",
            "abcdef.txt",
            {"split_mode": "positions", "delimiter": "3*|*5", "template": "$3$2$1"},
            "efcdab.txt",
        ),
        ("extension", "a.jpg.JPG", {"change": False, "remove_duplicates": True}, "a.JPG"),
        ("extension", "a.txt", {"text": "jpg", "append": True}, "a.txt.jpg"),
        ("strip", "abc123.txt", {"digits": True}, "abc.txt"),
        ("strip", "001a001.txt", {"digits": True, "position": "leading"}, "a001.txt"),
        ("strip", "a\u200bb.txt", {"unicode_range": "200B-200D"}, "ab.txt"),
        ("case", "hello DVD.TXT", {"mode": "title", "fragments": "DVD", "extension_case": "lower"}, "Hello DVD.txt"),
        ("case", "iPad.TXT", {"mode": "none"}, "iPad.TXT"),
        ("number", "a.txt", {"start": 12, "system": "roman"}, "XIIa.txt"),
        ("number", "a.txt", {"start": 3, "pad": True, "width": 3}, "003a.txt"),
        ("padding", "a01b002.txt", {"remove_zeros": True, "pad_numbers": False}, "a1b2.txt"),
        ("padding", "a.txt", {"pad_numbers": False, "pad_text": True, "length": 4, "characters": "xy"}, "xyxa.txt"),
        ("cleanup", " A (x(y))  B.txt", {"round": True}, "A B.txt"),
        ("cleanup", "a_b_v1.2.txt", {"replace_chars": "_.", "skip_versions": True}, "a b v1.2.txt"),
        ("translit", "Äpfel.txt", {"alphabet": "ä=ae", "auto_case": True}, "Aepfel.txt"),
        ("translit", "AE.txt", {"alphabet": "ä=ae", "direction": "backward"}, "Ä.txt"),
        ("translit", "ab.txt", {"alphabet": "a=b\nb=c", "auto_case": False}, "bc.txt"),
        ("date", "photo2024-01-31.txt", {"months": 1, "format": "yyyy-mm-dd"}, "photo2024-02-29.txt"),
        ("date", "bad2023-02-29.txt", {}, "bad2023-02-29.txt"),
        ("userinput", "a.txt", {"names": "First\nSecond"}, "First.txt"),
        ("mapping", "old.txt", {"mapping": "old\tnew\n"}, "new.txt"),
        ("mapping", "A old B.txt", {"mapping": "old\tnew\n", "partial": True}, "A new B.txt"),
    ],
)
def test_rule_behavior(kind, name, options, expected):
    assert rename(kind, name, **options) == expected


def test_registry_fields_and_preset_roundtrip():
    rules = []
    for kind, definition in REGISTRY.items():
        fields = {key for _, section in definition.sections for key in section}
        assert fields | {"skip_extension"} >= definition.defaults.keys()
        rule = RuleSpec(kind, behavior="renamer", options=definition.defaults)
        validate_rule(rule)
        rules.append(rule)
    assert parse_preset(preset_data("All rules", rules)) == ("All rules", rules)
    old = {"version": 1, "name": "Old", "rules": [{"kind": "insert", "options": {"index": 0}}]}
    assert parse_preset(old)[1][0].behavior == "legacy"


def test_stateful_rules():
    context = Evaluation()
    rule = RuleSpec("number", behavior="renamer", options={"repeat": 2, "reset_every": 3})
    assert [apply_rule("a.txt", rule, 0, context=context) for _ in range(5)] == [
        "1a.txt",
        "1a.txt",
        "2a.txt",
        "1a.txt",
        "1a.txt",
    ]
    rule = RuleSpec("mapping", behavior="renamer", options={"mapping": "a\tb"})
    context = Evaluation()
    assert apply_rule("a.txt", rule, 0, context=context) == "b.txt"
    assert apply_rule("a.txt", rule, 0, context=context) == "a.txt"
    context = Evaluation()
    rule = RuleSpec("randomize", behavior="renamer", options={"unique": True, "length": 1})
    results = [apply_rule("a.txt", rule, 0, context=context) for _ in range(10)]
    assert len(set(results)) == 10
    assert apply_rule("a.txt", rule, 0, context=context) in results


def test_metadata_basic_and_hash(tmp_path):
    path = tmp_path / "café.txt"
    path.write_bytes(b"abc")
    metadata = Metadata(datetime(2026, 10, 2, 12, 30), "paste")
    assert metadata.expand(":File_BaseName:-:File_SizeBytes:", str(path)) == "café-3"
    assert metadata.get("Hash_MD5", str(path)) == "900150983cd24fb0d6963f7d28e17f72"
    assert metadata.get("Clipboard", "") == "paste"
    assert metadata.get("Date_Now", "") == "2026-10-02 12-30-00"
    assert len(CATALOG) >= 140
    with pytest.raises(ValueError, match="Unknown"):
        metadata.get("Wrong", str(path))


def test_torrent_adapter():
    result = torrent_data(b"d4:infod6:lengthi3e4:name3:abcee")
    assert result["Name"] == "abc"
    assert result["TotalSizeBytes"] == 3
    assert len(result["Hash"]) == 40


def test_edge_cases_and_time_formats():
    assert rename("strip", "ABCabc.txt", english=True, case_sensitive=True) == ".txt"
    assert rename("replace", "abc.txt", find="*", replacement="X", wildcards=True) == "X.txt"
    assert (
        rename("date", "2026-10-02 12:34:56.txt", find_formats="yyyy-mm-dd hh:mm:ss", format="hh:mm:ss")
        == "12:34:56.txt"
    )
    assert (
        rename("date", "Fri 02 Oct 2026.txt", find_formats="ddd dd mmm yyyy", format="yyyy-mm-dd") == "2026-10-02.txt"
    )
    assert rename("number", "a.txt", start=101, system="chinese") == "一百零一a.txt"


@pytest.mark.skipif(not tool_path("rule_runtime"), reason="Native runtime must be built")
def test_batch_sequences_skip_excluded_files(make_entry):
    from dataclasses import replace

    from file_renamer.planner import build_plan

    entries = [make_entry("one.txt"), make_entry("two.txt"), make_entry("three.txt")]
    entries[1] = replace(entries[1], included=False)
    rules = [
        RuleSpec(
            "pascal",
            behavior="renamer",
            options={"script": "begin FileName:=IntToStr(GetCurrentMarkedFileIndex)+'-'+FileName; end."},
        )
    ]
    plan = build_plan(entries, rules)
    assert [__import__("pathlib").Path(row.destination).name for row in plan.files] == [
        "1-one.txt",
        "two.txt",
        "2-three.txt",
    ]
    assert not any(row.error for row in plan.files)
    assert build_plan(entries, rules) == plan


@pytest.mark.skipif(not tool_path("rule_runtime"), reason="Native runtime must be built")
def test_native_regex_and_pascal():
    assert rename("regex", "café12.txt", pattern=r"(.+)(\d{2})", replacement="$2-$1") == "12-café.txt"
    assert rename("regex", "aa.txt", pattern="a", replacement="x") == "xx.txt"
    with PascalSession() as session:
        session.compile("begin FileName := WideReplaceStr(FileName, 'a', 'é'); end.")
        assert (
            session.evaluate("begin FileName := WideReplaceStr(FileName, 'a', 'é'); end.", "a.txt", Evaluation())
            == "é.txt"
        )
        with pytest.raises(ValueError, match="Line"):
            session.compile("begin broken := ; end.")
        with pytest.raises(ValueError):
            session.compile("begin DeleteFile('a'); end.")


@pytest.mark.skipif(not tool_path("rule_runtime"), reason="Native runtime must be built")
@pytest.mark.parametrize(
    "source,expected",
    [
        ("begin FileName := WideReverseString('abc'); end.", "cba"),
        ("begin FileName := WideCopyRight('abcdef',2,3); end.", "cde"),
        ("begin FileName := WideTrimChars('---a__','-_'); end.", "a"),
        ("begin FileName := IntToStr(RomanToInt('XLII')); end.", "42"),
        ("begin FileName := Base64Encode('abc'); end.", "YWJj"),
        ("begin FileName := URLDecode('a+b%20c',True); end.", "a b c"),
        ("begin FileName := URLEncode('a b',True); end.", "a+b"),
        ("begin FileName := BoolToStr(IsWideCharUpper(WideChr(196))); end.", "True"),
        ("begin FileName := FormatDateTime('yyyy-mm-dd',IncMonth(EncodeDate(2024,1,31),1)); end.", "2024-02-29"),
        ("begin FileName := IntToStr(DayOfWeek(EncodeDate(2026,10,2))); end.", "5"),
        ("begin FileName := ReplaceRegEx('a12','(a)([0-9]+)','$2-$1',True,True); end.", "12-a"),
        (
            "var A:TWideStringArray; begin A:=WideSplitString('a_b_c','_'); FileName:=WideJoinStrings(A,'-'); end.",
            "a-b-c",
        ),
        (
            "var A:TWideStringArray; begin A:=MatchesRegEx('a1 b2','[a-z][0-9]',True); "
            "FileName:=WideJoinStrings(A,'-'); end.",
            "a1-b2",
        ),
        ("begin SetGlobalVar('n',12); FileName:=IntToStr(GetGlobalVar('n')); end.", "12"),
    ],
)
def test_pascal_function_families(source, expected):
    with PascalSession() as session:
        assert session.evaluate(source, "a.txt", Evaluation()) == expected


@pytest.mark.skipif(not tool_path("rule_runtime"), reason="Native runtime must be built")
def test_pascal_examples_compile_and_state_resets():
    from file_renamer.rule_controls import script_examples

    with PascalSession() as session:
        for source in script_examples().values():
            session.compile(source)
        script = "var Counter:Integer; begin Counter:=Counter+1; FileName:=IntToStr(Counter); end."
        assert [session.evaluate(script, "a", Evaluation()) for _ in range(3)] == ["1", "2", "3"]
    with PascalSession() as session:
        assert session.evaluate(script, "a", Evaluation()) == "1"


@pytest.mark.skipif(not tool_path("rule_runtime"), reason="Native runtime must be built")
def test_pascal_binary_read(tmp_path):
    path = tmp_path / "binary.dat"
    path.write_bytes(b"\x00\xff\x01")
    with PascalSession() as session:
        assert (
            session.evaluate(
                "begin FileName:=Base64Encode(FileReadContent(FilePath)); end.", "a", Evaluation(path=str(path))
            )
            == "AP8B"
        )


@pytest.mark.skipif(not tool_path("exiftool"), reason="Metadata tools must be built")
def test_metadata_content_and_exif(tmp_path):
    Image = pytest.importorskip("PIL.Image")

    path = tmp_path / "image.jpg"
    image = Image.new("RGB", (30, 20), "blue")
    exif = Image.Exif()
    exif[271], exif[272], exif[36867] = "Example", "Camera", "2026:10:02 12:30:00"
    image.save(path, exif=exif)
    metadata = Metadata()
    assert metadata.get("Image_Width", str(path)) == "30"
    assert metadata.get("Image_Height", str(path)) == "20"
    assert metadata.get("BinarySign_Extension", str(path)) == "jpg"
    assert metadata.get("EXIF_Model", str(path)) == "Camera"
    assert metadata.get("EXIF_Date", str(path)) == "2026-10-02 12-30-00"
