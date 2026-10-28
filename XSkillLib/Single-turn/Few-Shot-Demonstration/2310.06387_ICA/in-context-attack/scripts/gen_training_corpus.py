#!/usr/bin/env python3
"""Generate a real ICA training corpus for 2310.06387.

ICA (In-Context Attack) is a DETERMINISTIC / template attack: the payload is the
multi-turn chat prefix built by `attack.build_messages` — k harmful
query+compliant-response demonstration pairs prepended as prior turns, then the
target harmful request. There is no attacker LLM, so the "generator" is the ICA
template construction itself (seeded for reproducibility, though deterministic).

This script imports attack.py and reuses its REAL functions (load_dataset,
load_demonstrations, build_messages); it does not reimplement the attack. One
genuine constructed payload per AdvBench goal, over the FULL 520-row set.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

METHOD_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(METHOD_DIR / "scripts"))

import attack  # noqa: E402

PAPER_ID = attack.PAPER_ID
METHOD = "ica"
SHOTS = 5  # strongest available prefix (all 5 reconstructed demonstrations)
SEED = 20260630
MIN_LEN = 15

REFUSAL_LEADS = (
    "i'm sorry", "i am sorry", "i cannot", "i can't", "i can not",
    "i will not", "i won't", "i'm unable", "i am unable", "sorry, but",
    "as an ai", "i must decline", "i'm not able", "i am not able",
)

OUT = METHOD_DIR / "data" / "training_corpus" / f"sft_{METHOD}.json"


def render_payload(messages: list[dict[str, str]]) -> str:
    """Flatten the ICA multi-turn prefix into the genuine attack-prompt text."""
    parts = []
    for m in messages:
        role = "User" if m["role"] == "user" else "Assistant"
        parts.append(f"{role}: {m['content']}")
    return "\n\n".join(parts)


def is_leading_refusal(text: str) -> bool:
    head = text.strip().lower()[:60]
    return any(head.startswith(p) for p in REFUSAL_LEADS)


def main() -> None:
    random.seed(SEED)
    dataset = attack.load_dataset(attack.DEFAULT_DATASET)
    demos = attack.load_demonstrations(attack.DEFAULT_DEMOS)
    demo_queries = {d["query"].strip().lower() for d in demos[:SHOTS]}

    total_attempted = len(dataset)
    rows: list[dict] = []
    seen_payloads: set[str] = set()
    seen_goals: set[str] = set()
    dropped = {"empty": 0, "too_short": 0, "leading_refusal": 0,
               "degenerate_echo": 0, "duplicate": 0}

    for row in dataset:
        goal = row["request"].strip()
        gkey = goal.lower()

        # degenerate-echo: a target goal identical to one of the demo queries
        if gkey in demo_queries:
            dropped["degenerate_echo"] += 1
            continue
        if gkey in seen_goals:
            dropped["duplicate"] += 1
            continue

        messages = attack.build_messages(demos, SHOTS, goal)
        payload = render_payload(messages)

        if not payload.strip():
            dropped["empty"] += 1
            continue
        if len(payload.strip()) < MIN_LEN:
            dropped["too_short"] += 1
            continue
        # The compliant demo responses quote "Sure, here ..." (anti-refusal
        # framing); only drop if the constructed payload itself LEADS with a
        # genuine refusal, which a template prefix never does.
        if is_leading_refusal(payload):
            dropped["leading_refusal"] += 1
            continue
        if payload in seen_payloads:
            dropped["duplicate"] += 1
            continue

        seen_payloads.add(payload)
        seen_goals.add(gkey)
        rows.append({
            "row_id": row["row_id"],
            "goal": goal,
            "shots": SHOTS,
            "messages": messages,
            "attack_prompt": payload,
        })

    distinct = len({r["attack_prompt"] for r in rows})
    header = {
        "paper_id": PAPER_ID,
        "method": METHOD,
        "generator_model": (
            f"deterministic ICA template (attack.build_messages, {SHOTS}-shot "
            "in-context demonstration prefix; no attacker LLM)"
        ),
        "count": len(rows),
        "dropped": sum(dropped.values()),
        "dropped_detail": dropped,
        "total_attempted": total_attempted,
        "distinct_outputs": distinct,
        "seed": SEED,
        "payload_field": "attack_prompt",
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(header, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"attempted={total_attempted} kept={len(rows)} "
          f"dropped={sum(dropped.values())} {dropped} distinct={distinct}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
