#!/usr/bin/env python3
"""One-off converter: backfill canonical OpenAI chat-message fields.

Adds `model_input_messages` (the full OpenAI [{role, content}] conversation sent
to the target, ending on the final user trigger) and `model_output_text` (the
final harmful response, == final_response) to every case of already-saved CIA
result JSONs. `turns` is kept untouched as supplementary per-turn detail.

Derivation reuses cia.input_messages_from_turns() so new-run and converted
schemas are byte-identical. Idempotent: re-running overwrites the same fields.

Usage:
  $PY scripts/convert_result_messages.py results/*.json
  ($PY = shared XSkillForge/.venv/bin/python)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cia import input_messages_from_turns  # noqa: E402


def convert_file(path: Path) -> tuple[int, int]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    system_prompt = str(
        (doc.get("run_parameters") or {}).get("system_prompt")
        or "You are a helpful assistant."
    )
    cases = doc.get("results") or []
    added = 0
    for case in cases:
        turns = case.get("turns") or []
        final = case.get("final_response") or ""
        if turns:
            case["model_input_messages"] = input_messages_from_turns(turns, system_prompt)
        else:
            # aux-refused / provider_error: no target conversation happened.
            case["model_input_messages"] = (
                [{"role": "system", "content": system_prompt}] if system_prompt else []
            )
        case["model_output_text"] = final
        added += 1
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return added, len(cases)


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit("usage: convert_result_messages.py <result.json> ...")
    for arg in argv:
        p = Path(arg)
        n, total = convert_file(p)
        print(f"{p.name}: added model_input_messages+model_output_text to {n}/{total} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
