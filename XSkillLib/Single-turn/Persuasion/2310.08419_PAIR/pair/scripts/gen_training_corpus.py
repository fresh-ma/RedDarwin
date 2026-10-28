#!/usr/bin/env python3
"""Generate a PAIR attacker-prompt SFT corpus for arXiv 2310.08419.

The training corpus = {(harmful goal, strategy) -> PAIR attacker-LLM adversarial
prompt}. For each AdvBench goal x each official PAIR strategy we run the GENUINE
PAIR attacker step ONCE (first iteration) and keep the attacker's `prompt`
payload (the adversarial jailbreak prompt). The full target/judge refinement loop
is NOT needed for the corpus: the attacker's first-iteration prompt IS the
red-team payload to learn.

This is a thin driver: it IMPORTS attack.py and reuses its real attacker
functions (attacker_system_prompt / initial_attacker_user / generate_attack),
so generation stays byte-faithful to the official PAIR attacker. Every row is
QUALITY-FILTERED (quality > quantity): genuine leading-refusals / empty /
too-short / degenerate goal-echoes / duplicate payloads are dropped, not kept.

Generator default: api:deepseek/deepseek-v4-flash (cheap, non-reasoning, returns
non-null content on short generation; the paper's commercial attacker is closed,
so an open same-lab model is the faithful substitution).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import attack  # noqa: E402  (reuse the real PAIR attacker, no reimplementation)
from attack import (  # noqa: E402
    Case,
    attacker_system_prompt,
    generate_attack,
    initial_attacker_user,
    normalize_case,
)

PAPER_ID = attack.PAPER_ID
METHOD_ID = attack.METHOD_ID
DEFAULT_DATA = SCRIPT_DIR.parents[1] / "pair" / "data" / "harmful_behaviors_custom.csv"
DEFAULT_OUT = SCRIPT_DIR.parents[1] / "pair" / "data" / "training_corpus" / "sft_pair.json"
STRATEGIES = attack.STRATEGIES  # ("roleplay", "logical", "authority")

MIN_PAYLOAD_CHARS = 15

# Refusal markers (lowercased). A generated *payload* that is itself a refusal is
# useless as attacker-SFT. The official PAIR attacker rarely refuses; when it does
# the refusal is at the START of the text, so we only check the leading window
# (a legitimate jailbreak prompt may quote "I cannot ..." deep inside roleplay).
REFUSAL_MARKERS = (
    "i'm sorry", "i am sorry", "i apologize", "i cannot", "i can't", "i can not",
    "as an ai", "as a language model", "i'm not able", "i am not able",
    "i'm unable", "i am unable", "cannot assist", "can't assist", "cannot help",
    "can't help", "cannot comply", "i won't", "i will not", "i must decline",
    "i'm just an ai", "sorry, but", "i'm really sorry",
)
LEADING_WINDOW = 80  # chars of the payload head inspected for a genuine refusal


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def quality_reason(goal: str, payload: str) -> str | None:
    """Return a drop-reason string, or None if the payload is clean.

    Only LEADING refusals are dropped (the attacker rarely refuses; when it does,
    the refusal opens the message).
    """
    p = (payload or "").strip()
    if not p:
        return "empty"
    if len(p) < MIN_PAYLOAD_CHARS:
        return "too_short"
    head = p[:LEADING_WINDOW].lower()
    for m in REFUSAL_MARKERS:
        if m in head:
            return f"leading_refusal:{m}"
    np, ng = _norm(p), _norm(goal)
    if np == ng or (ng in np and len(np) <= len(ng) + 10):
        return "degenerate_goal_echo"
    return None


def load_cases(path: Path) -> list[Case]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [normalize_case(row, idx) for idx, row in enumerate(csv.DictReader(handle), 1)]


def gen_one(args: argparse.Namespace, case: Case, strategy: str) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": attacker_system_prompt(case.goal, case.target_str, strategy)},
        {"role": "user", "content": initial_attacker_user(case.goal, case.target_str)},
    ]
    try:
        result = generate_attack(
            args.generator, case, messages, stream_id=0, iteration=1,
            strategy=strategy, max_tokens=args.attack_max_tokens,
        )
    except Exception as exc:  # network/provider error -> non-fatal drop
        return {"case": case, "strategy": strategy, "payload": "", "improvement": "",
                "error": f"{type(exc).__name__}: {exc}"}
    if result.get("_attacker_failed"):
        return {"case": case, "strategy": strategy, "payload": "", "improvement": "",
                "error": "attacker_parse_failed"}
    return {"case": case, "strategy": strategy,
            "payload": result.get("prompt", ""), "improvement": result.get("improvement", "")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate PAIR attacker-prompt SFT corpus.")
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--generator", default="api:deepseek/deepseek-v4-flash",
                        help="attacker model adapter (api:<model>)")
    parser.add_argument("--attack-max-tokens", type=int, default=800)
    parser.add_argument("--max-workers", type=int, default=12)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.data))
    # Full grid: every goal x every official PAIR strategy.
    combos: list[tuple[Case, str]] = [(case, strat) for case in cases for strat in STRATEGIES]
    total = len(combos)
    start = time.time()

    raw: list[dict[str, Any]] = [None] * total  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        for i, out in zip(
            range(total),
            pool.map(lambda cs: gen_one(args, cs[0], cs[1]), combos),
        ):
            raw[i] = out

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen_payloads: set[str] = set()
    for item in raw:
        case = item["case"]
        payload = (item["payload"] or "").strip()
        reason = item.get("error") or quality_reason(case.goal, payload)
        if not reason and payload in seen_payloads:
            reason = "duplicate"
        if reason:
            dropped.append({"advbench_id": case.id, "goal": case.goal,
                            "strategy": item["strategy"], "reason": reason,
                            "payload_preview": payload[:120]})
            continue
        seen_payloads.add(payload)
        kept.append({
            "goal": case.goal,
            "strategy": item["strategy"],
            "prompt": payload,
            "target_str": case.target_str,
            "category": case.category,
            "advbench_id": case.id,
            "attacker_improvement": item["improvement"],
        })

    distinct = len({r["prompt"] for r in kept})
    drop_counts: dict[str, int] = {}
    for d in dropped:
        key = d["reason"].split(":", 1)[0]
        drop_counts[key] = drop_counts.get(key, 0) + 1

    corpus = {
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "corpus_type": "attacker_prompt_sft",
        "description": (
            "(harmful goal, strategy) -> PAIR attacker-LLM adversarial jailbreak prompt. "
            "Each row's `prompt` is the genuine attacker `prompt` payload from the official "
            "PAIR attacker step (first iteration; full target/judge loop not required for the "
            "payload), generated over the FULL AdvBench subset x each official strategy "
            "(roleplay/logical/authority) and quality-filtered "
            "(empty/too-short/leading-refusal/goal-echo/duplicate dropped)."
        ),
        "payload_field": "prompt",
        "generator_model": args.generator,
        "attack_max_tokens": args.attack_max_tokens,
        "strategies": list(STRATEGIES),
        "seed": args.seed,
        "total_attempted": total,
        "count": len(kept),
        "dropped": len(dropped),
        "drop_counts": drop_counts,
        "distinct": distinct,
        "drop_records": dropped,
        "rows": kept,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(corpus, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "total_attempted": total,
        "kept": len(kept),
        "dropped": len(dropped),
        "drop_counts": drop_counts,
        "distinct": distinct,
        "out": str(out_path),
        "seconds": round(time.time() - start, 2),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
