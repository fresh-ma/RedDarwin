---
name: renellm
description: "Run paper-local ReNeLLM Code: LLM rewrite operations, harmfulness check, scenario nesting, target call, and response judge."
metadata:
  paper: "2311.08268_nested-prompt-jailbreak"
  case_type: black_box_generator_loop
  access: black_box
  artifact_bundle: [official_advbench_data, rewrite_model, target_model, judge_model, rewrite_trace]
  execution_mode: [inspect, wiring_check_fake, live_api]
  evidence_level: model_substitution_run
  mechanism: rewrite plus scenario nesting
  script: "scripts/attack.py"
  fidelity_level: paper_algorithm_code
  judge: "official binary GPT harm classifier (OpenRouter deepseek/deepseek-v4-flash)"
  result: "results/RESULT_2026-06-25.md — v4-flash faithful ASR 0.23 (7/30); mythomax attacker ~0.8"
  taxonomy_label: llm-assisted-prompt-attack
  status: ready_to_use
---

# ReNeLLM Attack Script

This paper-local Code package implements ReNeLLM's algorithm: randomly select
rewrite operations, check that the rewritten prompt preserves harmful intent,
nest it in one of the paper's three scenarios, query a target model, and judge
the target response. The default dataset is the official AdvBench CSV copied
from `NJUNLP/ReNeLLM` into the method-local `assets/advbench/` directory.

Fidelity: `paper_algorithm_code`. The 6 rewrite-operation prompts, 3 scenario
templates, the binary GPT harmfulness judge, and the `TEST_PREFIXES` refusal gate
are ported verbatim from `NJUNLP/ReNeLLM` (commit `a61c39e`, cloned to
`.workspace/external/renellm-official`). A run that uses DeepSeek for
rewrite/judge/target is a model-substitution result, not the paper's exact
GPT-3.5/Claude-2/GPT-4 stack.

## Endpoints (important)

- **Target + rewrite model** → OpenRouter `api:<model>` (`--base-url
  https://openrouter.ai/api/v1`, `OPENROUTER_API_KEY`).
- **Harmfulness judge** → OpenRouter `deepseek/deepseek-chat` (`--judge-base-url
  https://openrouter.ai/api/v1`, `OPENROUTER_API_KEY`). This is the default judge
  routing and is verified to return the binary 0/1 label with no 403.
  Do **not** route the judge to OpenAI-direct: that account's quota is exhausted
  (`429 insufficient_quota`) and the OpenRouter `openai/*` route 403s harmful-judge
  prompts. `api_chat` retries transient 429/5xx/timeout failures with exponential
  backoff so a single hiccup no longer drops a case.

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/models.py` walks up to find it) — no per-skill `.env`,
no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

```bash
cd XSkillLib/Single-turn/Scenario-Nesting/2311.08268_ReNeLLM/renellm
$PY scripts/attack.py smoke >/dev/null                                   # wiring check (fake)
$PY scripts/attack.py inspect --sample-rows 3 --out /tmp/renellm_inspect.json

# Clean completion run: 20 goals per scenario x 2 scenarios, deepseek judge on
# OpenRouter (key from global XSkillForge/.env). Two scenario batches are merged
# into one result file (>=20x>=2).
$PY scripts/attack.py run \
  --target api:deepseek/deepseek-chat \
  --rewrite-model api:deepseek/deepseek-chat \
  --judge-model api:deepseek/deepseek-chat \
  --scenario code_completion \
  --iterations 3 --sample 20 --seed 20260609 --request-delay 0.3 \
  --out /tmp/renellm_A.json
$PY scripts/attack.py run \
  --target api:deepseek/deepseek-chat \
  --judge-model api:deepseek/deepseek-chat \
  --scenario text_continuation \
  --iterations 3 --sample 20 --seed 20260610 --request-delay 0.3 \
  --out /tmp/renellm_B.json
# then merge A+B -> results/renellm_deepseek_40x2_<date>.json
```

The summary reports a **dual metric**: `asr_refusal_bypass` (KW-ASR family,
over-counts) and `asr_content_harmful` (the paper's GPT-ASR, binary judge).
`run --target fake` is blocked unless `--wiring-check` is set; fake output is a
wiring check only and is never Code evidence.
