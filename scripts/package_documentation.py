"""Stage only the public, user-facing documentation in native packages."""
from __future__ import annotations

import shutil
import stat
from pathlib import Path

PUBLIC_DOCS = (
    "APPEARANCE.md",
    ".nojekyll", "LINUX_BUILD.md", "PRESETS.md", "RELEASE.md", "RULE_BEHAVIOR.md",
    "VALIDATION.md", "example-preset.toml", "icon.svg", "index.html",
    "linux-screenshot.png", "screenshot.png", "style.css",
)
ROOT_DOCUMENTS = {
    "README.md": "README.md",
    "LICENSE": "LICENSE",
    "LICENSE.txt": "LICENSE",
    "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
}


def reject_link(path: Path) -> None:
    """Reject symbolic links and Windows junctions, including broken links."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise RuntimeError(f"Documentation path must not be a link: {path}")


def stage_documentation(root: Path, bundle: Path) -> None:
    root, bundle = root.absolute(), bundle.absolute()
    if bundle == root or not bundle.is_relative_to(root):
        raise RuntimeError("Documentation bundle must stay inside the project")
    for path in (bundle, *bundle.parents):
        reject_link(path)
        if path == root:
            break
    if not bundle.is_dir() or not bundle.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("Documentation bundle directory is missing or outside the project")
    source_docs, target_docs = root / "docs", bundle / "docs"
    reject_link(source_docs)
    reject_link(target_docs)
    if target_docs.exists() and not target_docs.is_dir():
        raise RuntimeError("Packaged documentation destination must be a directory")
    sources = [root / name for name in ROOT_DOCUMENTS.values()]
    sources += [source_docs / name for name in PUBLIC_DOCS]
    for path in sources:
        reject_link(path)
        if not path.is_file():
            raise FileNotFoundError(f"Required package documentation is missing: {path}")
    for name in ROOT_DOCUMENTS:
        reject_link(bundle / name)
        if (bundle / name).exists() and not (bundle / name).is_file():
            raise RuntimeError(f"Packaged documentation destination must be a file: {name}")
    # Validate the absolute deletion target before replacing an earlier docs tree.
    if target_docs.resolve().parent != bundle.resolve():
        raise RuntimeError("Packaged documentation escaped the bundle")
    if target_docs.exists():
        shutil.rmtree(target_docs)
    target_docs.mkdir()
    for name in PUBLIC_DOCS:
        shutil.copy2(source_docs / name, target_docs / name)
    for destination, source in ROOT_DOCUMENTS.items():
        shutil.copy2(root / source, bundle / destination)


def verify_documentation(bundle: Path, source_root: Path) -> None:
    """Check the actual package, including README's local MIT license link."""
    docs = bundle / "docs"
    reject_link(docs)
    if not docs.is_dir() or {path.name for path in docs.iterdir()} != set(PUBLIC_DOCS):
        raise RuntimeError("Packaged documentation does not match the public file list")
    expected = {f"docs/{name}": f"docs/{name}" for name in PUBLIC_DOCS} | ROOT_DOCUMENTS
    for destination, source in expected.items():
        path = bundle / destination
        reject_link(path)
        if not path.is_file() or path.read_bytes() != (source_root / source).read_bytes():
            raise RuntimeError(f"Packaged documentation differs from its source: {destination}")
