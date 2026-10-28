#!/usr/bin/env python3
"""Build a training_corpus for DeepInception (2311.03191).

DeepInception's payload-generation step is DETERMINISTIC: the attacker prompt is
a fixed nested-scene template filled per harmful goal (no LLM in the loop). We
therefore reuse the real attack functions from attack.py
(`load_dataset`, `render_deepinception_prompt`, `normalize_goal`) to emit ONE
genuine constructed attacker prompt per goal over the FULL benchmark
(AdvBench 520 + JailbreakBench 100), then quality-filter.

Because generation is deterministic, there is no provider/API call and no
sampling randomness; `--seed` only fixes the (already deterministic) row order.
The corpus is an attacker-prompt SFT set: input = harmful goal, output = the
DeepInception nested-scene attacker prompt.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

METHOD_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = METHOD_DIR / "data"
OUT_PATH = DATA_DIR / "training_corpus" / "sft_deepinception.json"
MIN_LEN = 15


def _load_attack_module():
    spec = importlib.util.spec_from_file_location(
        "deepinception_attack", METHOD_DIR / "scripts" / "attack.py"
    )
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
    parser = argparse.ArgumentParser(description="Generate DeepInception training_corpus.")
    parser.add_argument("--seed", type=int, default=0, help="Fixes row order (generation is deterministic).")
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    atk = _load_attack_module()

    datasets = [
        ("advbench", DATA_DIR / "advbench_harmful_behaviors.json"),
        ("jailbreakbench", DATA_DIR / "jailbreakbench_behaviors.json"),
    ]

    scene = atk.DEFAULT_SCENE
    layers = atk.DEFAULT_LAYERS
    chars = atk.DEFAULT_CHARACTERS

    attempted = 0
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    dropped = {"empty": 0, "too_short": 0, "leading_refusal": 0, "degenerate_echo": 0, "duplicate": 0}

    for ds_name, ds_path in datasets:
        for row in atk.load_dataset(ds_path):
            attempted += 1
            goal = row["request"]
            attack_prompt = atk.render_deepinception_prompt(
                goal, scene_type=scene, num_layers=layers, num_characters=chars
            )
            text = attack_prompt.strip()
            if not text:
                dropped["empty"] += 1
                continue
            if len(text) < MIN_LEN:
                dropped["too_short"] += 1
                continue
            if is_leading_refusal(text):
                dropped["leading_refusal"] += 1
                continue
            if text == goal.strip():
                dropped["degenerate_echo"] += 1
                continue
            if text in seen:
                dropped["duplicate"] += 1
                continue
            seen.add(text)
            kept.append(
                {
                    "id": f"{ds_name}-{row['row_id']}",
                    "dataset": ds_name,
                    "category": row["category"],
                    "goal": goal,
                    "attack_prompt": text,
                    "scene_type": scene,
                    "num_layers": layers,
                    "num_characters": chars,
                }
            )

    # Deterministic order; --seed kept for interface consistency.
    kept.sort(key=lambda r: r["id"])

    corpus = {
        "paper_id": atk.PAPER_ID,
        "method": atk.METHOD_NAME,
        "task": "attacker_prompt_sft",
        "description": (
            "Attacker-prompt SFT corpus for DeepInception. Each row maps a harmful goal "
            "to the DeepInception nested-scene attacker prompt (deterministic template render, "
            "verbatim official `inception_attack` wording, scene=science fiction, layers=5, "
            "characters=5). input field = `goal`, output field = `attack_prompt`."
        ),
        "generator_model": (
            "deterministic:DeepInception render_deepinception_prompt "
            "(no LLM; official template fc5689e, scene=science fiction/layers=5/characters=5)"
        ),
        "source_backing": {"official_repo": atk.OFFICIAL_REPO, "official_commit": atk.OFFICIAL_COMMIT},
        "config": {"scene_type": scene, "num_layers": layers, "num_characters": chars},
        "datasets": ["AdvBench harmful_behaviors (520)", "JailbreakBench behaviors (100)"],
        "counts": {"attempted": attempted, "kept": len(kept), "dropped": dropped},
        "input_field": "goal",
        "output_field": "attack_prompt",
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
