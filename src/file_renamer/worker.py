"""Private newline-delimited JSON protocol for isolated preview evaluation."""

from __future__ import annotations

from pathlib import Path

from .models import RuleSpec, entry_from_dict
from .planner import build_plan
from .storage import atomic_json, read_json


def main(request_path: str, response_path: str) -> int:
    try:
        request = read_json(Path(request_path))
        # The GUI starts the evaluation deadline after interpreter imports have completed.
        Path(response_path + ".ready").touch()
        result = build_plan(
            [entry_from_dict(row) for row in request["entries"]],
            [RuleSpec(**rule) for rule in request["rules"]],
            request["revision"],
            request.get("snapshot"),
        )
        atomic_json(Path(response_path), {"plan": result.to_dict()})
        return 0
    except Exception as exc:
        atomic_json(Path(response_path), {"error": str(exc)})
        return 1
