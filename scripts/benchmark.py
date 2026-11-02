"""Exercise preview, commit, and undo on an isolated batch of synthetic files."""
from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from file_renamer.filesystem import scan_paths
from file_renamer.models import RuleSpec
from file_renamer.planner import build_plan
from file_renamer.transactions import TransactionManager


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10000)
    args = parser.parse_args()
    if not 1 <= args.count <= 100000:
        parser.error("count must be between 1 and 100000")
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="batch-check-", dir=output) as directory:
        batch = Path(directory) / "files"
        batch.mkdir()
        for index in range(args.count):
            (batch / f"photo_{index:05}.jpg").write_bytes(f"content-{index}".encode())
        start = time.monotonic()
        entries, errors = scan_paths([str(batch)], False)
        assert not errors
        scanned = time.monotonic()
        plan = build_plan(entries, [RuleSpec("number", options={"width": 5})])
        assert not plan.errors and len(plan.changes) == args.count
        previewed = time.monotonic()
        print(f"{args.count:,} files: scan {scanned-start:.2f}s, preview {previewed-scanned:.2f}s", flush=True)
        manager = TransactionManager(Path(directory) / "data/last-rename.json")

        def progress(done, total):
            if done % 5000 == 0:
                print(f"  {done:,}/{total:,} filesystem moves", flush=True)

        result = manager.execute(plan, progress=progress)
        assert result.success, result.message
        committed = time.monotonic()
        for index, row in enumerate(plan.files):
            assert Path(row.destination).read_bytes() == f"content-{index}".encode()
        result = manager.restore(progress=progress)
        assert result.success, result.message
        undone = time.monotonic()
        for index, entry in enumerate(entries):
            assert Path(entry.path).read_bytes() == f"content-{index}".encode()
        assert len(list(batch.iterdir())) == args.count
        print(f"Commit {committed-previewed:.2f}s; verify and undo {undone-committed:.2f}s. All contents preserved.")


if __name__ == "__main__":
    main()
