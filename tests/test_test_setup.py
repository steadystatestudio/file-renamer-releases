from pathlib import Path
from types import SimpleNamespace

import conftest
import pytest


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    (root / "tests").mkdir(parents=True)
    monkeypatch.setattr(conftest, "__file__", str(root / "tests" / "conftest.py"))
    return root


@pytest.mark.parametrize("existing_parent", [False, True])
def test_default_basetemp_prepares_parent(checkout, existing_parent):
    artifacts = checkout / "artifacts"
    if existing_parent:
        artifacts.mkdir()
        (artifacts / "keep.txt").write_text("keep", encoding="utf-8")
    config = SimpleNamespace(option=SimpleNamespace(basetemp=None))

    conftest.pytest_configure(config)

    target = Path(config.option.basetemp)
    assert target == artifacts / "pytest-temp"
    assert artifacts.is_dir()
    assert not target.exists()
    # pytest creates basetemp without parents=True, including on a fresh checkout.
    target.mkdir(mode=0o700)
    if existing_parent:
        assert (artifacts / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_explicit_basetemp_is_preserved(checkout):
    explicit = str(checkout / "custom-temp")
    config = SimpleNamespace(option=SimpleNamespace(basetemp=explicit))

    conftest.pytest_configure(config)

    assert config.option.basetemp == explicit
    assert not (checkout / "artifacts").exists()


@pytest.mark.parametrize("link_path", ["artifacts", "artifacts/pytest-temp"])
def test_unsafe_basetemp_is_rejected(checkout, tmp_path, link_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = checkout / link_path
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink privilege is not available")
    config = SimpleNamespace(option=SimpleNamespace(basetemp=None))

    with pytest.raises(RuntimeError, match="Unsafe test temporary directory"):
        conftest.pytest_configure(config)

    assert config.option.basetemp is None
    assert list(outside.iterdir()) == []
