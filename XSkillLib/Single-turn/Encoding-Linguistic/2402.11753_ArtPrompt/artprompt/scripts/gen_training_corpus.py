#!/usr/bin/env python3
"""Generate a red-team training_corpus for the ArtPrompt unit.

ArtPrompt is a DETERMINISTIC two-step transform (no attacker LLM): mask the
sensitive word of a harmful instruction, then re-render that word as VISIBLE
ASCII art inside the official ``vitc_horizontal`` cloaked-prompt template. The
reusable red-team artifact is therefore the genuine cloaked ASCII-art payload
itself, one per harmful goal, produced verbatim by the official procedure.

This script reuses the real attack functions from ``attack.py`` (no
re-implementation): the dataset masker (``choose_mask_word``) + the official
horizontal renderer (``render_messages`` -> ``cloaked_prompt`` ->
``generate_alphabet_ascii``). It walks the FULL harmful_behaviors_custom.csv,
emits one cloaked payload per goal, quality-filters, and writes the corpus.

generator_model = deterministic ArtPrompt procedure (no LLM).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import attack  # the paper-local ArtPrompt port (same scripts/ dir)

METHOD_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = METHOD_DIR / "data" / "training_corpus" / "sft_artprompt.json"

# Default attack configuration: official deterministic transform.
FONT = "gen"          # GPT-generated 5x5 ASCII grid (no external font dep)
DIRECTION = "h"       # vitc_horizontal (paper default)
MASKER = "dataset"    # per-row sensitive-word category column (deterministic)
MIN_LEN = 15


def _masker_args() -> argparse.Namespace:
    """Minimal namespace for the deterministic dataset masker."""
    return argparse.Namespace(mask_word=None, masker=MASKER, masker_model=None)


def build_rows() -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = attack.normalize_rows(attack.read_rows(attack.DEFAULT_DATASET), "auto")
    margs = _masker_args()
    seen_payloads: set[str] = set()
    kept: list[dict[str, Any]] = []
    stats = {"attempted": 0, "empty": 0, "too_short": 0, "refusal": 0,
             "degenerate_echo": 0, "duplicate": 0, "kept": 0}

    for row in rows:
        stats["attempted"] += 1
        goal = row["goal"]
        mask_word, masker_meta = attack.choose_mask_word(row, margs)
        messages, masked = attack.render_messages(goal, mask_word, FONT, direction=DIRECTION)
        payload = messages[0]["content"]

        # Quality filters (the ASCII-art block is NOT a refusal).
        if not payload.strip():
            stats["empty"] += 1
            continue
        if len(payload.strip()) < MIN_LEN:
            stats["too_short"] += 1
            continue
        # Leading-refusal guard: deterministic payloads never start with a
        # refusal, but check honestly against the official refusal list.
        head = payload.lstrip()[:40]
        if any(head.startswith(r.strip()) for r in attack.DICT_JUDGE_REFUSALS):
            stats["refusal"] += 1
            continue
        # Degenerate-echo: the cloaked payload must actually transform the goal
        # (contain the ASCII art + [MASK]), not just echo the raw instruction.
        if "[MASK]" not in masked or "ascii art" not in payload.lower():
            stats["degenerate_echo"] += 1
            continue
        if payload in seen_payloads:
            stats["duplicate"] += 1
            continue
        seen_payloads.add(payload)

        kept.append({
            "id": row["id"],
            "goal": goal,
            "category": row.get("category", ""),
            "mask_word": mask_word,
            "masked_instruction": masked,
            "font": FONT,
            "direction": DIRECTION,
            "masker": masker_meta["masker"],
            "payload": payload,
        })
        stats["kept"] += 1

    return kept, stats


def main() -> None:
    kept, stats = build_rows()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    corpus = {
        "schema": "red_team_training_corpus.v1",
        "paper_id": attack.PAPER_ID,
        "method": attack.METHOD_ID,
        "attack_family": "ascii_art_obfuscation (ArtPrompt)",
        "generator_model": "deterministic ArtPrompt procedure (no attacker LLM)",
        "generator_procedure": (
            "Official two-step transform: dataset masker (per-row sensitive-word "
            "category column) -> vitc_horizontal cloaked-prompt template with the "
            "masked word re-rendered as the GPT-generated 5x5 ASCII-art grid (font=gen)."
        ),
        "source_dataset": "harmful_behaviors_custom.csv (AdvBench-derived, 50)",
        "config": {"font": FONT, "direction": DIRECTION, "masker": MASKER},
        "payload_field": "payload",
        "count": len(kept),
        "filter_stats": stats,
        "rows": kept,
    }
    OUT_PATH.write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(kept)} rows -> {OUT_PATH}")
    print("stats:", json.dumps(stats))


if __name__ == "__main__":
    main()
