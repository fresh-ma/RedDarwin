#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate a real training_corpus for the FlipAttack unit (2410.02832).

FlipAttack is DETERMINISTIC: FlipAttack.generate() builds the attack prompt by
pure character/word reversal of the harmful goal plus the official attack-disguise
+ flipping-guidance system/user strings. There is NO attacker LLM. So each SFT row
is a genuine, faithfully-produced jailbreak payload — no model calls, no sampling.

Procedure: load the FULL AdvBench harmful_behaviors set (520 goals) via attack.py's
own readers, then for each goal emit one flip-disguised attack payload. The
(mode x cot x langgpt x few_shot) prompt-pack config is assigned by a seeded
round-robin so the corpus exercises the whole official prompt pack (FWO/FCW/FCS/FMM
x CoT/LangGPT/few-shot) while staying one-payload-per-goal.

payload_field = "attack_prompt" (the rendered system+user FlipAttack prompt).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

import attack  # sibling module; reuse real funcs, no reimplementation

SEED = 20260630
_HERE = Path(__file__).resolve()
_METHOD_ROOT = _HERE.parents[1]
OUT_PATH = _METHOD_ROOT / "data" / "training_corpus" / "sft_flipattack.json"

# Official prompt-pack axes (FlipAttack modes x variants). All deterministic.
MODES = ["FWO", "FCW", "FCS", "FMM"]
COT = [True, False]
LANGGPT = [True, False]
FEW_SHOT = [True, False]


def build_configs() -> list[dict[str, Any]]:
    cfgs = []
    for m in MODES:
        for c in COT:
            for lg in LANGGPT:
                for fs in FEW_SHOT:
                    cfgs.append({"mode": m, "cot": c, "langgpt": lg, "few_shot": fs})
    return cfgs


def load_goals() -> tuple[list[dict[str, Any]], str]:
    ns = argparse.Namespace(dataset="advbench", goals=None, sample=None, seed=SEED)
    rows, source = attack.read_rows(ns, smoke_only=False)
    return rows, source


def is_degenerate(payload: str, goal: str) -> bool:
    """Drop a payload that just echoes the goal with no real transformation."""
    return payload.strip().lower() == goal.strip().lower()


def main() -> None:
    rng = random.Random(SEED)
    configs = build_configs()
    rng.shuffle(configs)

    rows, source = load_goals()

    kept: list[dict[str, Any]] = []
    drops = {"empty": 0, "too_short": 0, "leading_refusal": 0, "degenerate_echo": 0, "duplicate": 0}
    seen: set[str] = set()
    attempted = 0

    for idx, row in enumerate(rows):
        attempted += 1
        cfg = configs[idx % len(configs)]
        goal = row["goal"]
        atk = attack.FlipAttack(cfg["mode"], cfg["cot"], cfg["langgpt"], cfg["few_shot"], "gpt")
        _, messages = atk.generate(goal)
        payload = attack.messages_to_text(messages)

        # --- genuine quality filter ---
        if not payload.strip():
            drops["empty"] += 1
            continue
        if len(payload.strip()) < 15:
            drops["too_short"] += 1
            continue
        low = payload.strip().lower()
        if low.startswith(("i'm sorry", "i am sorry", "i cannot", "i can't", "sorry,", "as an ai")):
            drops["leading_refusal"] += 1
            continue
        if is_degenerate(payload, goal):
            drops["degenerate_echo"] += 1
            continue
        if payload in seen:
            drops["duplicate"] += 1
            continue
        seen.add(payload)

        kept.append({
            "id": f"flipattack-{idx}",
            "goal": goal,
            "category": row.get("category", ""),
            "source_row": row.get("source_row"),
            "mode": cfg["mode"],
            "cot": cfg["cot"],
            "langgpt": cfg["langgpt"],
            "few_shot": cfg["few_shot"],
            "system_prompt": messages[0]["content"],
            "user_prompt": messages[1]["content"],
            "attack_prompt": payload,
            "generator_model": "deterministic (attack.FlipAttack.generate; no LLM)",
        })

    distinct = len({r["attack_prompt"] for r in kept})
    out = {
        "paper_id": attack.PAPER_ID,
        "method": attack.METHOD_ID,
        "capability": "flipattack_flip_disguise_payload_generation",
        "attack_family": "text_flipping_obfuscation (FlipAttack; char/word reversal, trivially-reversible left-side-noise)",
        "description": (
            "Deterministic FlipAttack jailbreak payloads: harmful goal -> flip-disguised "
            "(char/word reversal) + official attack-disguise/flipping-guidance prompt. SFT "
            "corpus for a red-team model that emits FlipAttack payloads. No attacker LLM."
        ),
        "generator_model": "deterministic (attack.FlipAttack.generate; no LLM)",
        "generator_procedure": (
            "attack.read_rows(advbench full 520) -> attack.FlipAttack(mode,cot,langgpt,few_shot)"
            ".generate(goal) -> attack.messages_to_text(messages); seeded round-robin over the "
            "(mode x cot x langgpt x few_shot) official prompt-pack configs, one payload per goal"
        ),
        "seed": SEED,
        "query_learning": "zero-shot",
        "payload_field": "attack_prompt",
        "modes": MODES,
        "dataset": source,
        "total": len(kept),
        "positive": len(kept),
        "negative": 0,
        "distinct_payloads": distinct,
        "counts": {
            "attempted": attempted,
            "kept": len(kept),
            "dropped": attempted - len(kept),
            "distinct_payloads": distinct,
            "drops": drops,
        },
        "training_use": (
            "attacker_prompt_sft: input=harmful goal, output=FlipAttack flip-disguised "
            "jailbreak payload (rendered system+user attack prompt)"
        ),
        "rows": kept,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    print(f"attempted={attempted} kept={len(kept)} dropped={attempted - len(kept)} distinct={distinct}")
    print(f"drops={drops}")


if __name__ == "__main__":
    main()
