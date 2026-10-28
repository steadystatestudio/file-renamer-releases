import subprocess
from types import SimpleNamespace

import pytest

from file_renamer.metadata import Metadata, child_options, tool_path


def test_metadata_disables_external_exiftool_configuration(tmp_path, monkeypatch):
    source = tmp_path / "photo.png"
    source.write_bytes(b"source bytes stay unchanged")
    calls = []

    def run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(stdout=b'[{"PNG:ImageWidth": 2}]')

    monkeypatch.setattr("file_renamer.metadata.tool_path", lambda _: "bundled-exiftool")
    monkeypatch.setattr("file_renamer.metadata.subprocess.run", run)

    assert Metadata().get("Image_Width", str(source)) == "2"
    command, options = calls[0]
    # ExifTool requires -config before every other option, including -json.
    assert command[:3] == ["bundled-exiftool", "-config", ""]
    assert command[-2:] == ["--", str(source)]
    assert options["timeout"] == 30
    assert source.read_bytes() == b"source bytes stay unchanged"


@pytest.mark.skipif(not tool_path("exiftool"), reason="Bundled ExifTool is not built")
def test_real_metadata_ignores_personal_config(tmp_path, monkeypatch):
    from PySide6.QtGui import QImage

    config_home = tmp_path / "exiftool-home"
    config_home.mkdir()
    marker = tmp_path / "config-executed.txt"
    (config_home / ".ExifTool_config").write_text(
        'open(my $fh, ">", $ENV{"RENAMER_TEST_CONFIG_SENTINEL"}) or die $!;\n'
        'print $fh "Configuration executed"; close($fh);\n1;\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("EXIFTOOL_HOME", str(config_home))
    monkeypatch.setenv("RENAMER_TEST_CONFIG_SENTINEL", str(marker))
    tool = tool_path("exiftool")
    # Verify the isolated test config really is found without the safety option.
    subprocess.run([tool, "-ver"], capture_output=True, check=True, timeout=30, **child_options())
    assert marker.read_text(encoding="utf-8") == "Configuration executed"
    marker.unlink()

    source = tmp_path / "photo.png"
    picture = QImage(2, 3, QImage.Format_RGB32)
    picture.fill(0xFF0000)
    assert picture.save(str(source))
    original = source.read_bytes()
    assert Metadata().get("Image_Width", str(source)) == "2"
    assert not marker.exists()
    assert source.read_bytes() == original
