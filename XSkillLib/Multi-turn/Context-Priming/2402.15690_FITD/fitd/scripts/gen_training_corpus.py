#!/usr/bin/env python3
"""Build a training_corpus for FITD / Foot-In-The-Door (2402.15690).

FITD's payload-generation step (the staged split instance, Sec 4.3) is
DETERMINISTIC: the attacker turns are fixed background -> villain -> plot
templates filled per harmful goal (no auxiliary LLM in this reproduction; see
red_team_capability.json fidelity note). We therefore reuse the real attack
functions from attack.py (`load_rows`, `base_prompts`) to emit ONE genuine
constructed staged-attack payload per goal over the FULL AdvBench-520 pool,
then quality-filter.

Because generation is deterministic, there is no provider/API call and no
sampling randomness; `--seed` only fixes the (already deterministic) row order.
The corpus is an attacker-prompt SFT set: input = harmful goal, output =
`attack_prompt` (the assembled background/villain/plot staged escalation).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

METHOD_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = METHOD_DIR / "data"
FULL_POOL = DATA_DIR / "advbench_full_520.csv"
OUT_PATH = DATA_DIR / "training_corpus" / "sft_fitd.json"
MIN_LEN = 15


def _load_attack_module():
    spec = importlib.util.spec_from_file_location("fitd_attack", METHOD_DIR / "scripts" / "attack.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


REFUSAL_PREFIXES = (
    "i'm sorry",
    "i am sorry",
    "i cannot",
    "i can't",
    "i can not",
    "i am unable",
    "i'm unable",
    "as an ai",
    "i won't",
    "i will not",
    "sorry, but",
)


def is_leading_refusal(text: str) -> bool:
    head = text.strip().lower()[:60]
    return any(head.startswith(p) for p in REFUSAL_PREFIXES)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate FITD training_corpus.")
    parser.add_argument("--seed", type=int, default=0, help="Fixes row order (generation is deterministic).")
    parser.add_argument("--samples", default=str(FULL_POOL), help="Full AdvBench seed-goal pool.")
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    atk = _load_attack_module()

    # FULL dataset: sample_rows=0 -> all rows.
    rows = atk.load_rows(Path(args.samples), 0)

    attempted = 0
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    dropped = {"empty": 0, "too_short": 0, "leading_refusal": 0, "degenerate_echo": 0, "duplicate": 0}

    for idx, row in enumerate(rows):
        attempted += 1
        goal = row["goal"]
        category = row.get("category")
        staged = atk.base_prompts(goal, category)
        # Assembled staged-escalation payload: the three user turns FITD sends.
        attack_prompt = "\n\n".join(
            f"[{p['stage']}] {p['prompt']}" for p in staged
        ).strip()

        if not attack_prompt:
            dropped["empty"] += 1
            continue
        if len(attack_prompt) < MIN_LEN:
            dropped["too_short"] += 1
            continue
        if is_leading_refusal(attack_prompt):
            dropped["leading_refusal"] += 1
            continue
        if attack_prompt == goal.strip():
            dropped["degenerate_echo"] += 1
            continue
        if attack_prompt in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(attack_prompt)
        kept.append(
            {
                "id": f"advbench-{idx:03d}",
                "dataset": "advbench",
                "category": category,
                "goal": goal,
                "attack_prompt": attack_prompt,
                "staged_prompts": staged,
                "split_instance": "background_villain_plot",
            }
        )

    # Deterministic order; --seed kept for interface consistency.
    kept.sort(key=lambda r: r["id"])

    corpus = {
        "paper_id": atk.PAPER_ID,
        "method": atk.METHOD_ID,
        "task": "attacker_prompt_sft",
        "description": (
            "Attacker-prompt SFT corpus for FITD (Foot-In-The-Door, 2402.15690). Each row maps a "
            "harmful goal to the FITD staged-escalation payload (deterministic split instance, "
            "Sec 4.3: background -> villain -> plot, filled per goal). input field = `goal`, "
            "output field = `attack_prompt`."
        ),
        "generator_model": (
            "deterministic:FITD base_prompts split-instance render (no LLM; "
            "background/villain/plot template tables from attack.py)"
        ),
        "datasets": ["AdvBench harmful_behaviors (520)"],
        "counts": {"attempted": attempted, "kept": len(kept), "dropped": dropped},
        "input_field": "goal",
        "output_field": "attack_prompt",
        "payload_field": "attack_prompt",
        "rows": kept,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(corpus, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    distinct = len({r["attack_prompt"] for r in kept})
    print(f"attempted={attempted} kept={len(kept)} dropped={dropped} distinct_attack_prompt={distinct}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
