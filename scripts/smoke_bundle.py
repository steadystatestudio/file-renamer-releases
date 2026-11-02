"""Check packaged preview helpers and a synthetic GUI rename/Undo workflow."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from dataclasses import asdict
from pathlib import Path

from file_renamer.filesystem import regular_identity
from file_renamer.models import FileEntry, RuleSpec
from file_renamer.smoke import tiff_fixture


def image_fixture() -> bytes:
    """A 2×3 red RGB PNG using only stdlib; verification hosts need no GUI wheel."""
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    header = struct.pack('!IIBBBBB', 2, 3, 8, 2, 0, 0, 0)
    pixels = (b'\x00' + b'\xff\x00\x00' * 2) * 3
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def main():
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="renamer-bundle-test-", dir=executable.parent) as directory:
        root = Path(directory)
        source = root / "blue_jacket.JPG"
        source.write_bytes(b"unchanged")
        request = {
            "revision": 42,
            "entries": [asdict(FileEntry(str(source), regular_identity(source)))],
            "rules": [
                asdict(RuleSpec("rearrange", options={"template": "{2}_{1}"})),
                asdict(RuleSpec("repair", options={"platform": "Windows-compatible"})),
                asdict(RuleSpec("insert", options={"text": "new_"})),
            ],
        }
        (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
        command = [str(executable), "--preview-worker", str(root / "request.json"), str(root / "response.json")]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        result = subprocess.run(command, timeout=30, cwd=root, **options)
        assert result.returncode == 0, result.returncode
        response = json.loads((root / "response.json").read_text(encoding="utf-8"))
        assert response["plan"]["revision"] == 42
        row = response["plan"]["files"][0]
        assert row["destination"] == str(root / "new_jacket_blue.JPG") and not row["error"], response
        assert source.read_bytes() == b"unchanged" and not (root / "new_jacket_blue.JPG").exists()
        request["rules"] = [
            asdict(RuleSpec("regex", behavior="renamer", options={"pattern": "blue", "replacement": "navy"})),
            asdict(
                RuleSpec(
                    "pascal", behavior="renamer", options={"script": "begin FileName := WideUpperCase(FileName); end."}
                )
            ),
            asdict(RuleSpec("insert", behavior="renamer", options={"text": ":Hash_MD5:_"})),
        ]
        (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
        result = subprocess.run(command, timeout=30, cwd=root, **options)
        assert result.returncode == 0, result.returncode
        response = json.loads((root / "response.json").read_text(encoding="utf-8"))
        row = response["plan"]["files"][0]
        assert row["destination"].endswith("_NAVY_JACKET.JPG") and not row["error"], response
        picture = root / "picture.png"
        picture.write_bytes(image_fixture())
        request["entries"] = [asdict(FileEntry(str(picture), regular_identity(picture)))]
        request["rules"] = [
            asdict(RuleSpec("insert", behavior="renamer", options={"text": ":Image_Width:_:BinarySign_Extension:_"}))
        ]
        (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
        result = subprocess.run(command, timeout=30, cwd=root, **options)
        assert result.returncode == 0, result.returncode
        response = json.loads((root / "response.json").read_text(encoding="utf-8"))
        row = response["plan"]["files"][0]
        assert row["destination"].endswith("2_png_picture.png") and not row["error"], response
        picture = root / "picture.tif"
        picture.write_bytes(tiff_fixture())
        request["entries"] = [asdict(FileEntry(str(picture), regular_identity(picture)))]
        request["rules"] = [asdict(RuleSpec("insert", behavior="renamer", options={
            "text": ":Image_Width:_:Image_Height:_:TIFF_Model:_"}))]
        (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
        result = subprocess.run(command, timeout=30, cwd=root, **options)
        assert result.returncode == 0, result.returncode
        response = json.loads((root / "response.json").read_text(encoding="utf-8"))
        row = response["plan"]["files"][0]
        assert row["destination"].endswith("2_3_StudioQA_picture.tif") and not row["error"], response
        assert picture.read_bytes() == tiff_fixture()
        environment = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("FILE_RENAMER_SMOKE_PLATFORM", "offscreen"))
        result = subprocess.run(
            [str(executable), "--smoke-workflow", str(root / "ui-check")],
            timeout=120, cwd=root, env=environment, **options
        )
        if result.returncode != 0:
            error = root / "ui-check/error.txt"
            raise RuntimeError(error.read_text(encoding="utf-8") if error.exists()
                               else f"Packaged GUI stopped with exit code {result.returncode}")
        assert (root / "ui-check/ui.png").stat().st_size > 1000
        receipt = json.loads((root / "ui-check/result.json").read_text(encoding="utf-8"))
        assert receipt["success"] and receipt["rename"] == receipt["undo"] == "passed"
        assert receipt["rule_creation"] == receipt["rule_editing"] == "passed"
        assert receipt["created_rule_kinds"] == ["insert", "replace"]
        assert receipt["tiff_metadata"] == "passed" and receipt["tiff_original_unchanged"]
        assert receipt["hashes_before"] == receipt["hashes_after"] and receipt["originals_unchanged"]
        assert not (root / "ui-check/application.lock").exists()
        if len(sys.argv) > 2:
            import shutil
            evidence = Path(sys.argv[2]).resolve()
            evidence.mkdir(parents=True, exist_ok=False)
            for name in ("ui.png", "ui-preview.png", "result.json"):
                shutil.copy2(root / "ui-check" / name, evidence / name)
    print("Packaged GUI, preview helpers, rename and Undo passed; original names and contents restored.")


if __name__ == "__main__":
    main()
