import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def app():
    from PySide6.QtWidgets import QApplication
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    return instance


@pytest.fixture
def make_entry(tmp_path):
    from file_renamer.filesystem import regular_identity
    from file_renamer.models import FileEntry

    def create(name, content=b"test content"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return FileEntry(str(path), regular_identity(path))

    return create


def pytest_configure(config):
    # Windows' default temporary directory is inside hidden AppData.
    if config.option.basetemp is None:
        root = Path(__file__).resolve().parents[1]
        target = root / "artifacts" / "pytest-temp"
        if not target.resolve().is_relative_to(root) or target.is_symlink():
            raise RuntimeError("Unsafe test temporary directory")
        # pytest creates basetemp itself, but requires its parent to exist.
        target.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(target)
