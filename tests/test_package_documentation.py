import importlib.util
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("package_documentation", ROOT / "scripts/package_documentation.py")
documentation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(documentation)


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "project"
    (root / "docs").mkdir(parents=True)
    for name in documentation.PUBLIC_DOCS:
        (root / "docs" / name).write_bytes(f"Public documentation: {name}".encode())
    (root / "README.md").write_text("[MIT](LICENSE)", encoding="utf-8")
    (root / "LICENSE").write_bytes((ROOT / "LICENSE").read_bytes())
    (root / "THIRD_PARTY_NOTICES.md").write_bytes((ROOT / "THIRD_PARTY_NOTICES.md").read_bytes())
    bundle = root / "dist/File-Renamer"
    bundle.mkdir(parents=True)
    return root, bundle


def test_staging_excludes_unlisted_docs_and_replaces_stale_tree(package):
    root, bundle = package
    (root / "docs/private-research.md").write_text("Must not ship", encoding="utf-8")
    (bundle / "docs/old-notes").mkdir(parents=True)
    (bundle / "docs/old-notes/stale.md").write_text("Must be removed", encoding="utf-8")
    documentation.stage_documentation(root, bundle)
    documentation.verify_documentation(bundle, root)
    assert not (bundle / "docs/private-research.md").exists()
    assert not (bundle / "docs/old-notes").exists()
    for name in ("PRESETS.md", "RULE_BEHAVIOR.md", "index.html", "screenshot.png", "style.css"):
        assert (bundle / "docs" / name).read_bytes() == (root / "docs" / name).read_bytes()
    assert (bundle / "README.md").read_text(encoding="utf-8") == "[MIT](LICENSE)"
    assert (bundle / "LICENSE").read_bytes() == (bundle / "LICENSE.txt").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert (bundle / "THIRD_PARTY_NOTICES.md").read_bytes() == (ROOT / "THIRD_PARTY_NOTICES.md").read_bytes()


@pytest.mark.parametrize("missing", ["docs/RULE_BEHAVIOR.md", "LICENSE"])
def test_missing_required_documentation_stops_before_replacing_existing_docs(package, missing):
    root, bundle = package
    (bundle / "docs").mkdir()
    sentinel = bundle / "docs/previous.md"
    sentinel.write_text("Previous package", encoding="utf-8")
    (root / missing).unlink()
    with pytest.raises(FileNotFoundError, match="Required package documentation"):
        documentation.stage_documentation(root, bundle)
    assert sentinel.read_text(encoding="utf-8") == "Previous package"


@pytest.mark.parametrize("path", ["LICENSE", "docs/RULE_BEHAVIOR.md", "docs/private-research.md"])
def test_package_verification_rejects_modified_or_extra_documentation(package, path):
    root, bundle = package
    documentation.stage_documentation(root, bundle)
    (bundle / path).write_text("Unexpected package content", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Packaged documentation"):
        documentation.verify_documentation(bundle, root)


@pytest.mark.parametrize("linked", ["source", "destination"])
def test_linked_documentation_is_rejected_without_touching_target(package, tmp_path, linked):
    root, bundle = package
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "keep.txt"
    sentinel.write_text("Preserve me", encoding="utf-8")
    path = root / "docs/RULE_BEHAVIOR.md" if linked == "source" else bundle / "docs"
    if linked == "source":
        path.unlink()
    try:
        path.symlink_to(sentinel if linked == "source" else external, target_is_directory=linked == "destination")
    except OSError as error:
        pytest.skip(f"Host cannot create a symbolic link: {error}")
    with pytest.raises(RuntimeError, match="must not be a link"):
        documentation.stage_documentation(root, bundle)
    assert sentinel.read_text(encoding="utf-8") == "Preserve me"


def test_windows_junction_is_rejected_before_removing_stale_docs(package, monkeypatch):
    root, bundle = package
    target = bundle / "docs"
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        if path == target:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(RuntimeError, match="must not be a link"):
        documentation.stage_documentation(root, bundle)


def test_bundle_outside_project_is_rejected(package, tmp_path):
    root, _ = package
    external = tmp_path / "external"
    external.mkdir()
    with pytest.raises(RuntimeError, match="inside the project"):
        documentation.stage_documentation(root, external)
    assert list(external.iterdir()) == []
