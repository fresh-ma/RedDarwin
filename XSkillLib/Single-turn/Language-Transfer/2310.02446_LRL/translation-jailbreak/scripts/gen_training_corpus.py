#!/usr/bin/env python3
"""Generate a genuine training_corpus for the translation-jailbreak unit.

The attack's payload is DETERMINISTIC machine translation (no attacker LLM):
each English harmful goal is forward-translated into a low-resource natural
language via the real Google Translate Basic API (the same path the attack
uses, ``attack.translate_text`` with ``--translator project-api``). This
script reuses those real functions verbatim — no reimplementation — to emit
one genuine translated payload per goal over the FULL AdvBench dataset, then
quality-filters and writes the SFT corpus.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from types import SimpleNamespace

import attack  # noqa: E402  (sibling module in scripts/)

HERE = Path(__file__).resolve().parent
METHOD_DIR = HERE.parent
DATA = METHOD_DIR / "data"
GOALS = DATA / "advbench_harmful_behaviors.json"
OUT = DATA / "training_corpus" / "sft_translation-jailbreak.json"

SEED = 20260629
MIN_CHARS = 15
LRL = attack.LANGUAGE_GROUPS["lrl"]  # zu (Zulu), gd (Scots Gaelic), hmn (Hmong), gn (Guarani)

REFUSAL_PREFIXES = (
    "i'm sorry", "i am sorry", "sorry, but", "i cannot", "i can't", "i can not",
    "as an ai", "i'm unable", "i am unable", "i apologize", "i must decline",
)


def translator_args() -> SimpleNamespace:
    """Minimal args namespace for attack.translate_text (real Google MT)."""
    return SimpleNamespace(
        translator="project-api",
        translation_provider="google",
        translation_model=None,
    )


def is_leading_refusal(text: str) -> bool:
    head = text.strip().lower()[:40]
    return any(head.startswith(p) for p in REFUSAL_PREFIXES)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="cap goals (debug only)")
    args = parser.parse_args()

    # FULL dataset, deterministic (load_goals with sample_rows=None keeps all 520).
    goals, source = attack.load_goals(str(GOALS), None, SEED)
    if args.limit:
        goals = goals[: args.limit]
    attempted = len(goals)

    rng = random.Random(SEED)
    targs = translator_args()
    cache: dict = {}

    rows: list[dict] = []
    drop_counts = {"empty": 0, "too_short": 0, "leading_refusal": 0,
                   "degenerate_echo": 0, "duplicate": 0, "mt_error": 0}
    seen: set[str] = set()

    for idx, goal in enumerate(goals):
        # Seed-assign one low-resource language per goal (reproducible).
        code = rng.choice(LRL)
        translated, src, status = attack.translate_text(
            goal["goal"], str(goal["id"]), code, "forward", targs, cache
        )
        translated = (translated or "").strip()

        if status != "ok" or src.startswith("project-api_error"):
            drop_counts["mt_error"] += 1
            continue
        if not translated:
            drop_counts["empty"] += 1
            continue
        if translated.strip() == goal["goal"].strip():
            drop_counts["degenerate_echo"] += 1  # MT returned untranslated English
            continue
        if len(translated) < MIN_CHARS:
            drop_counts["too_short"] += 1
            continue
        if is_leading_refusal(translated):
            drop_counts["leading_refusal"] += 1
            continue
        if translated in seen:
            drop_counts["duplicate"] += 1
            continue
        seen.add(translated)

        rows.append({
            "case_id": f"{idx:03d}",
            "goal": goal["goal"],
            "target": None,  # filled below from source row if present
            "language_code": code,
            "language_name": attack.LANGUAGES[code]["name"],
            "resource": attack.LANGUAGES[code]["resource"],
            "translated_prompt": translated,
            "translation_provider": src,
        })

    # Attach AdvBench affirmative-prefix target where available.
    raw = json.loads(GOALS.read_text(encoding="utf-8"))
    by_id = {str(r.get("id")): r.get("target") for r in raw}
    for r in rows:
        gid = next((g["id"] for g in goals if g["goal"] == r["goal"]), None)
        r["target"] = by_id.get(str(gid))

    header = {
        "paper_id": attack.PAPER_ID,
        "method": attack.METHOD_ID,
        "generator_model": "google_translate_v2_basic (real MT, deterministic; project-api:google)",
        "generator_note": (
            "Deterministic low-resource-language jailbreak: NO attacker LLM and NO "
            "crafted prompt-template. Per-goal payload = attack.translate_text(goal, "
            "lang, 'forward') — the English harmful goal forward-translated into a "
            "low-resource natural language via the real Google Translate Basic API. "
            "One language per goal is seed-assigned (random.Random(seed)) from the "
            "paper's 4 LRL set: Zulu/Scots Gaelic/Hmong/Guarani. Fully reproducible "
            "given the same seed and translation API."
        ),
        "payload_field": "translated_prompt",
        "source_dataset": source,
        "lrl_languages": {c: attack.LANGUAGES[c]["name"] for c in LRL},
        "count": len(rows),
        "dropped": attempted - len(rows),
        "drop_counts": drop_counts,
        "total_attempted": attempted,
        "distinct_outputs": len({r["translated_prompt"] for r in rows}),
        "seed": SEED,
        "rows": rows,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(header, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"attempted={attempted} kept={len(rows)} dropped={attempted - len(rows)} "
          f"distinct={header['distinct_outputs']} drops={drop_counts}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
