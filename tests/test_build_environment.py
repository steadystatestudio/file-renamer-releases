import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace


def test_windows_build_ignores_unrelated_dll_search_paths(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/build_environment.py"
    spec = importlib.util.spec_from_file_location("build_environment_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("PATH", "unrelated-poppler;unrelated-libheif")
    monkeypatch.setenv("SystemRoot", "D:/CustomWindows")
    monkeypatch.setattr(module, "sys", SimpleNamespace(
        platform="win32", executable="C:/Python/venv/Scripts/python.exe", base_prefix="C:/Python"))
    environment = module.pyinstaller_environment()
    assert "unrelated" not in environment["PATH"]
    assert str(Path("D:/CustomWindows/System32")) in environment["PATH"]
    assert str(Path("C:/Python/venv/Scripts")) in environment["PATH"]
    assert os.environ["PATH"] == "unrelated-poppler;unrelated-libheif"
    module.sys.platform = "linux"
    assert module.pyinstaller_environment()["PATH"] == os.environ["PATH"]
