#!/usr/bin/env python3
"""Build a training_corpus for CodeChameleon (2402.16717).

CodeChameleon's payload-generation step is DETERMINISTIC: there is no attacker
LLM. Each harmful goal is transformed by a reversible custom encryption function
(default: binary_tree), the MATCHING Python decryption function is embedded
verbatim, and both are wrapped in the code-completion `ProblemSolver` scaffold
under the jailbreak system prompt (`code_sys_helpful`). The assembly is a static,
deterministic red-team recipe.

We reuse the REAL attack functions from attack.py (`read_rows`,
`get_encrypted_query`, `encrypted_to_text`, `build_prompt`, `CODE_SYS_HELPFUL`)
to emit ONE genuine constructed attack payload per goal over the FULL official
benchmark (all_problem.csv = 820 = AdvBench 520 + shadow_heldout 200 +
MaliciousInstruct 100), then quality-filter.

Because generation is deterministic, there is no provider/API call and no
sampling randomness; `--seed` only fixes the (already deterministic) row order.
The corpus is an attack-prompt SFT set: input = harmful goal, output = the
CodeChameleon encrypted code-completion attack payload (output field
`attack_prompt`).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

METHOD_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = METHOD_DIR / "data"
OUT_PATH = DATA_DIR / "training_corpus" / "sft_codechameleon.json"
GOALS_CSV = METHOD_DIR / "data" / "all_problem.csv"
MIN_LEN = 15
RULE = "binary_tree"  # attack.py default --rule
TEMPLATE = "code"     # attack.py default --template


def _load_attack_module():
    spec = importlib.util.spec_from_file_location(
        "codechameleon_attack", METHOD_DIR / "scripts" / "attack.py"
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
    parser = argparse.ArgumentParser(description="Generate CodeChameleon training_corpus.")
    parser.add_argument("--seed", type=int, default=0, help="Fixes row order (generation is deterministic).")
    parser.add_argument("--goals", default=str(GOALS_CSV))
    parser.add_argument("--rule", default=RULE)
    parser.add_argument("--template", default=TEMPLATE)
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    atk = _load_attack_module()

    rows, source = atk.read_rows(args.goals, smoke_only=False)

    attempted = 0
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    dropped = {"empty": 0, "too_short": 0, "leading_refusal": 0, "degenerate_echo": 0, "duplicate": 0}

    for row in rows:
        attempted += 1
        goal = row["goal"]
        encrypted = atk.get_encrypted_query(goal, args.rule)
        encrypted_text = atk.encrypted_to_text(encrypted)
        # Full genuine payload: jailbreak system prompt + code-completion scaffold
        # (embedded decryptor + encrypted goal), exactly as sent to the target.
        user_content = atk.build_prompt(encrypted_text, args.rule, args.template)
        attack_prompt = f"SYSTEM:\n{atk.CODE_SYS_HELPFUL}\n\nUSER:\n{user_content}".strip()

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
                "id": f"{row.get('category') or 'goal'}-{row['source_row']}",
                "dataset": row.get("category", ""),
                "goal": goal,
                "attack_prompt": attack_prompt,
                "encrypted_goal_text": encrypted_text,
                "rule": args.rule,
                "template": args.template,
            }
        )

    # Deterministic order; --seed kept for interface consistency.
    kept.sort(key=lambda r: (r["dataset"], r["id"]))

    corpus = {
        "paper_id": atk.PAPER_ID,
        "method": atk.METHOD_ID,
        "task": "attacker_prompt_sft",
        "description": (
            "Attack-payload SFT corpus for CodeChameleon. Each row maps a harmful goal to "
            "its CodeChameleon encrypted code-completion attack payload (deterministic assembly: "
            f"custom encryption rule='{args.rule}' + matching embedded Python decryptor + "
            "ProblemSolver code-completion scaffold + jailbreak system prompt code_sys_helpful, "
            "verbatim official wording). input field = `goal`, output field = `attack_prompt`."
        ),
        "generator_model": (
            f"deterministic:CodeChameleon build_prompt (no LLM; verbatim official port "
            f"huizhang-L/CodeChameleon@16a19920; rule={args.rule}/template={args.template}/"
            "include_system=True)"
        ),
        "source_backing": {
            "official_repo": "huizhang-L/CodeChameleon@16a19920",
            "official_files_ported": ["encrypt.py", "decrypt.py", "template.py", "utils.complete_format"],
            "dataset_artifact": source,
        },
        "config": {"rule": args.rule, "template": args.template, "include_system": True},
        "datasets": ["CodeChameleon all_problem.csv (820 = advbench 520 + shadow_heldout 200 + MaliciousInstruct 100)"],
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
