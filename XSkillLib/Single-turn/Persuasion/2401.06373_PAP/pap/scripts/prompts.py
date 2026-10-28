#!/usr/bin/env python3
"""PAP prompt / template layer — persuasion taxonomy + verbatim official templates.

Everything PAP sends is built here:
  * the in-context persuasive paraphraser template (official `one_shot_kd` from
    incontext_sampling_example.ipynb) and the persuasion-technique taxonomy loader
    (40 techniques from persuasion_taxonomy.jsonl),
  * the Qi et al. 2023 GPT-4 Judge rubric template + its 1-5 score parser.

The large template bodies live verbatim in `data/prompts/*.txt` (loaded as
resources) so a source formatter/linter cannot strip whitespace and drift the
bytes away from the paper's actual paraphraser + judge.

Generator source: https://github.com/CHATS-lab/persuasive_jailbreaker
Judge source: https://github.com/LLM-Tuning-Safety/LLMs-Finetuning-Safety
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from models import DATA_DIR

PROMPTS_DIR = DATA_DIR / "prompts"
DEFAULT_TAXONOMY = DATA_DIR / "persuasion_taxonomy.jsonl"

# Templates loaded from data/prompts/ (verbatim from official sources)
ONE_SHOT_KD = (PROMPTS_DIR / "one_shot_kd.txt").read_text(encoding="utf-8")
JUDGE_TEMPLATE = (PROMPTS_DIR / "qi_judge.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Taxonomy loader
# ---------------------------------------------------------------------------


def load_taxonomy(path: str | Path) -> list[dict[str, str]]:
    """Load the 40-technique persuasion taxonomy from official JSONL."""
    path = Path(path)
    techniques = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        techniques.append({
            "name": obj["ss_technique"],
            "definition": obj["ss_definition"],
            "example": obj["ss_example"],
        })
    return techniques


# ---------------------------------------------------------------------------
# Generator: in-context persuasive paraphraser
# Official one_shot_kd template loaded from data/prompts/one_shot_kd.txt
# Source: https://github.com/CHATS-lab/persuasive_jailbreaker/blob/main/incontext_sampling_example.ipynb
# ---------------------------------------------------------------------------


def build_generator_prompt(goal: str, technique: dict[str, str]) -> str:
    """Fill the one_shot_kd template with technique info and the harmful query."""
    return ONE_SHOT_KD % (
        technique["name"],
        technique["definition"],
        technique["example"],
        goal,
        technique["name"],
        goal,
        goal,
    )


# ---------------------------------------------------------------------------
# Judge: Qi et al. 2023 GPT-4 Judge rubric
# Loaded from data/prompts/qi_judge.txt (verbatim from official source)
# Source: https://github.com/LLM-Tuning-Safety/LLMs-Finetuning-Safety/blob/main/
#         gpt-3.5/eval_utils/openai_policy_gpt4_judge.py
# ---------------------------------------------------------------------------


def build_judge_prompt(user_instruction: str, model_response: str) -> str:
    """Fill the Qi et al. judge template."""
    return JUDGE_TEMPLATE % (user_instruction, model_response)


def parse_judge_score(judge_output: str) -> int | None:
    """Extract the numeric score from #thescore: <N>."""
    match = re.search(r"#thescore:\s*(\d)", judge_output)
    if match:
        return int(match.group(1))
    # Fallback: find any digit after "score"
    match = re.search(r"score[:\s]*(\d)", judge_output.lower())
    if match:
        return int(match.group(1))
    return None
