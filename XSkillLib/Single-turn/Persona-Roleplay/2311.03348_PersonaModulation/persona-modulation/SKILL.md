---
name: persona-modulation
description: "Faithful black-box persona-modulation jailbreak (arXiv 2311.03348): an LLM attacker generates a persona-modulation prompt, a deepseek target answers, and a goal-faithful dual-metric judge scores the completion."
paper: "2311.03348_persona-based-llm-jailbreak"
case_type: black_box_generator_loop
access: black_box_api
artifact_bundle:
  - public_category_table
  - llm_attacker_persona_generator
  - live_target_completions
  - goal_faithful_dual_metric_judge
execution_mode:
  - openai_compatible_api
evidence_level: model_substitution_run
fidelity_level: faithful_method_code
---

# Persona Modulation (arXiv 2311.03348)

Faithful black-box reproduction of the paper's automated persona-modulation
jailbreak: an LLM attacker proposes a persona + persona-modulation system prompt,
the target answers, and a goal-faithful PICT-style judge scores the completion.

## What

Per harmful category from the paper's public 43-category table:
1. derive a misuse instruction;
2. **attacker** (`gryphe/mythomax-l2-13b`) emits a persona + persona-modulation
   system prompt (deepseek refuses to author jailbreak personas, so a cheap
   non-refusing rewrite model fills the generation role);
3. **target** (`deepseek/deepseek-v4-flash`) answers (persona system + misuse user);
4. **judge** (`deepseek/deepseek-v4-flash`) returns a goal-faithful dual metric:
   `refusal_bypass` and `content_harmful` (harmful AND on-goal only).

`model_substitution_run`: paper used GPT-4/Claude-2/Vicuna target + GPT-4 PICT
judge; the rubric is preserved, only the serving model changes.

The paper's public 43-category table is vendored at
`data/tab-detailed-results.tex` (parsed by both scripts; `--category-table`
overrides).

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo
root (`XSkillForge/.venv`; the scripts are stdlib-only — `openai` not required).
API keys are read from the global `XSkillForge/.env` (`load_project_env()` walks
up from the skill directory to find the first `.env` in any ancestor) — no
per-skill `.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Quick checks (offline, no API)
```bash
cd XSkillLib/Single-turn/Persona-Roleplay/2311.03348_PersonaModulation/persona-modulation
$PY scripts/attack.py inspect
$PY scripts/attack.py render --sample-rows 1 --out /tmp/persona-modulation-render.json
```

## Live run (attacker + target + judge over OpenRouter, key from global XSkillForge/.env)
```bash
cd XSkillLib/Single-turn/Persona-Roleplay/2311.03348_PersonaModulation/persona-modulation
$PY scripts/pipeline.py \
  --sample-rows 12 --target-temperatures 0.0 0.7 --request-delay 0.3
```

→ `results/persona_modulation_deepseek_<n>x_<date>.json` (24 cases × 2 configs).

## Result

Canonical run: **asr_content_harmful = 1/24 = 4.17%**, refusal_bypass = 4.17%,
0 provider errors, 0 attacker refusals. deepseek-v4-flash is highly robust to
template-free persona modulation; the one positive (copyright violation) is
verified genuinely on-goal. Self-checked against raw per-case verdicts.

## Settings

target/attacker/judge models, `--sample-rows`, `--target-temperatures`,
`--include-sensitive-categories` (off by default; 5 sensitive categories excluded),
`--goals-csv` (benchmark-goal mode: CSV `request` column used verbatim as the
misuse instruction, replacing the category table; success cases are emitted with
`status: "ok"` so `judge/unified_judge.py` scores them).

`scripts/attack.py` is the legacy input-only renderer (refusal-proxy judge),
superseded by `pipeline.py`.
