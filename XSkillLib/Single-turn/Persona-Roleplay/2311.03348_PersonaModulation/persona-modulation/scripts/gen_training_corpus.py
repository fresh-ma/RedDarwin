#!/usr/bin/env python3
"""Generate a real training_corpus for the persona-modulation unit.

Thin wrapper around attack.py. The persona-modulation attack is DETERMINISTIC:
the target-facing jailbreak payload is rendered by attack.render_case() from the
paper's public PERSONA_SEEDS + PROMPT_STYLES templates and a per-category misuse
instruction. There is no attacker/generator LLM, so payloads are produced by the
genuine attack procedure (not sampled from a model).

One genuine payload per goal (= per harmful category), over the FULL category
table. The payload field is `model_input_text` (the rendered persona-modulation
prompt that is sent to the target).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import attack  # noqa: E402

SEED = 2311
METHOD_ROOT = attack.METHOD_ROOT
OUT_PATH = METHOD_ROOT / "data" / "training_corpus" / "sft_persona-modulation.json"
PAYLOAD_FIELD = "model_input_text"

# rotate persona + style deterministically across goals for variety
STYLES = ["system_role", "simulation", "expert_briefing"]
TARGET_FORMAT = "system_user"
PERSONA_COUNT = len(attack.PERSONA_SEEDS)


def is_refusal_leading(text: str) -> bool:
    return attack.refusal_proxy(text)


def is_degenerate_echo(text: str, goal: str) -> bool:
    # payload that is nothing but the goal string repeated
    body = text.strip()
    return body == goal.strip() or body.lower() == goal.strip().lower()


def main() -> int:
    # FULL dataset: include sensitive categories so every goal in the table is covered
    categories = attack.load_categories(attack.DEFAULT_CATEGORY_TABLE, include_sensitive=True)
    attempted = len(categories)

    rows: list[dict] = []
    seen: set[str] = set()
    dropped = {"leading_refusal": 0, "empty": 0, "too_short": 0, "degenerate_echo": 0, "duplicate": 0}

    for idx, category in enumerate(categories):
        persona_index = idx % PERSONA_COUNT
        style = STYLES[idx % len(STYLES)]
        case = attack.render_case(
            category=category,
            category_index=idx,
            persona_index=persona_index,
            style=style,
            target_format=TARGET_FORMAT,
        )
        payload = case[PAYLOAD_FIELD]
        goal = case["misuse_instruction"]

        if not payload or not payload.strip():
            dropped["empty"] += 1
            continue
        if is_refusal_leading(payload):
            dropped["leading_refusal"] += 1
            continue
        if len(payload.strip()) < 15:
            dropped["too_short"] += 1
            continue
        if is_degenerate_echo(payload, goal):
            dropped["degenerate_echo"] += 1
            continue
        key = payload.strip()
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)

        rows.append(
            {
                "goal": goal,
                "category": category,
                "persona_name": case["persona"]["name"],
                "prompt_style": style,
                "target_format": TARGET_FORMAT,
                PAYLOAD_FIELD: payload,
                "case_id": case["case_id"],
            }
        )

    distinct_payloads = len({r[PAYLOAD_FIELD].strip() for r in rows})

    corpus = {
        "schema_version": "training_corpus.v1",
        "method_id": METHOD_ROOT.name,
        "paper_id": attack.PAPER_ROOT.name,
        "task": "sft",
        "generator": "deterministic_public_method_renderer",
        "generator_model": "deterministic_public_method_renderer",
        "seed": SEED,
        "payload_field": PAYLOAD_FIELD,
        "goal_field": "goal",
        "source": {
            "attack_script": "scripts/attack.py",
            "function": "render_case",
            "category_table": attack.rel(attack.DEFAULT_CATEGORY_TABLE),
            "paper": attack.OFFICIAL_ARXIV,
        },
        "stats": {
            "attempted": attempted,
            "kept": len(rows),
            "dropped": dropped,
            "distinct_payloads": distinct_payloads,
        },
        "rows": rows,
    }

    attack.write_json(OUT_PATH, corpus)
    print(json.dumps({"out": str(OUT_PATH), "attempted": attempted, "kept": len(rows),
                      "dropped": dropped, "distinct_payloads": distinct_payloads}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
