---
name: echo-chamber
description: "Run the Echo Chamber multi-turn jailbreak loop with swappable attacker, target, and judge models."
metadata:
  paper: "2601.05742_echo-chamber-escalation-jailbreak"
  access: black_box
  mechanism: multi-turn seed/path/persuasion-cycle jailbreak
  script: "scripts/attack.py"
  official_repo: "NeuralTrust/echo-chamber"
  fidelity_level: partial_algorithm_code
  status: ready_to_run
  payload_contract:
    input: "A harmful goal, covert-objective seed, and maximum-turn configuration."
    output: "A multi-turn dialogue path culminating in a target response."
    retained_state: "Generated keywords, selected seed/path, full dialogue, and evaluation state."
    feedback_dependency: "later attacker prompts depend on target dialogue outcomes"
    composition_status: "not_composable"
---

# Echo Chamber Attack Script

Paper-local runner for the Echo Chamber multi-turn jailbreak. It follows the
official public implementation shape: rewrite a harmful task into a covert
objective, extract steering keywords, generate seed sentences, pick a promising
path, run a target dialogue, and evaluate the final response.

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/attack.py` `load_env` walks up from the skill dir to
find the first `.env` defining the key) — no per-skill `.env`, no `uv run`,
no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter

cd XSkillLib/Multi-turn/Crescendo/2601.05742_EchoChamber/echo-chamber

# Static preflight: local dataset/config only, no API calls.
$PY scripts/attack.py inspect

# Fast black-box run against DeepSeek V4 Flash.
$PY scripts/attack.py run \
  --sample 10 --max-turns 4 \
  --target api:deepseek/deepseek-v4-flash \
  --attacker-model api:deepseek/deepseek-v4-flash \
  --judge-model api:deepseek/deepseek-v4-flash \
  --out results/echo_chamber_deepseek-v4-flash_n10_$(date +%Y%m%d-%H%M%S).json
```

Dataset (full official 12-objective AdvBench selection) lives at `data/adv-bench.json`;
results land in `results/`; official source is preserved under `references/official/`.

The paper uses Gemini/GPT-family models. This runner keeps the role structure
but substitutes open/lab models by default and records the run as
`model_substitution_run`.
