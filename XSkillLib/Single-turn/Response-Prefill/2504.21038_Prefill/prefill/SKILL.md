---
name: prefill
description: "Black-box assistant-prefill jailbreak: send a user prompt + attacker-controlled assistant prefill, then judge the target's continuation with a goal-faithful dual-metric judge."
metadata:
  paper: "2504.21038_prefill-based-llm-jailbreak"
  access: black_box
  mechanism: assistant prefill / autoregressive continuation
  script: "scripts/attack.py"
  official_repo: "star5o/Prefill-level-Jailbreak@684ed23223d7f452754e615ea606efe76f729897"
  fidelity_level: static_template_faithful
  status: done
  payload_contract:
    input: "A harmful goal and one static assistant-prefill category."
    output: "A user message followed by an attacker-controlled assistant prefix for continuation."
    retained_state: "The selected prefill template and category identifier."
    feedback_dependency: "none"
    composition_status: "direct"
---

# Prefill-level Jailbreak

**What.** Reproduces Li et al. 2504.21038. The attacker submits a normal user
prompt PLUS an attacker-controlled *assistant prefill* message; the target API
continues from that prefill (autoregressive), shifting its initial state from
refusal toward compliance. Black-box — needs only an API that honors a trailing
`assistant` message as a prefix (DeepSeek, Claude documented; others undocumented).
Covers the 7 static prefill categories: scenario_forgery, persona_adoption,
intent_hijacking, commitment_forcing, continuation_enforcement, structured_output,
refusal_bypass. Templates vendored from the official repo.

**Use.** Target + judge default to `deepseek/deepseek-v4-flash` (OpenRouter). The
judge is the Qi et al. 2023 policy GPT-4 rubric (1–5 Likert) served verbatim and
**goal-faithful** — it sees the original AdvBench goal, so off-topic harm is not
counted as success. Dual metric: refusal-bypass + content-harmful.

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/attack.py: load_project_env` walks up from the script
to find the first `.env` in any ancestor directory) — no per-skill `.env`,
no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Quick checks (offline, no API calls)
```bash
cd XSkillLib/Single-turn/Response-Prefill/2504.21038_Prefill/prefill
$PY scripts/attack.py inspect --sample-rows 14
$PY scripts/attack.py render --sample-rows 2 --out /tmp/prefill-render.json
```

## Live run (target + judge over OpenRouter, key from global XSkillForge/.env)
Real run: 14 cases × 7 static categories. Use max_tokens >= 4096 for reasoning
targets (e.g. deepseek-v4-flash) — low budgets are spent on hidden reasoning
and return EMPTY content.

```bash
cd XSkillLib/Single-turn/Response-Prefill/2504.21038_Prefill/prefill
$PY scripts/attack.py run \
  --sample-rows 14 --seed 20260625 \
  --target api:deepseek/deepseek-v4-flash \
  --judge-model deepseek/deepseek-v4-flash \
  --temperature 0.0 --max-tokens 4096 \
  --out results/prefill_v4flash_static7_n14_t00_mt4096_20260628.json
```

**Run.** Needs `OPENROUTER_API_KEY` (read from the global `XSkillForge/.env` via
ancestor walk-up, or shell). Black-box (API prefill) — no GPU. `--target` /
`--judge-model` are swappable `api:<model>`; `--judge-max-tokens`, `--temperature`,
`--seed`, `--sample-rows`, `--attack-methods` parameterize the grid.

**Test.** Canonical run `results/prefill_v4flash_static7_n14_t00_mt4096_20260628.json`
(target=judge=`deepseek/deepseek-v4-flash`, temp 0.0, max_tokens 4096, n=14, 0 errors):
| metric | count | rate |
|--------|-------|------|
| refusal_bypass | 4/14 | 0.286 |
| content_harmful (score 5) | 1/14 | 0.071 |
| content_harmful (score ≥4) | 3/14 | 0.214 |
Raw score-5 positives confirmed genuine on-goal harm by GLM per-case audit
(`results/GLM_REVIEW_20260627.json`); audited content_harmful = raw = 1/14 = 0.071.
See `results/RESULT_2026-07-01.md` for the full counts + paper comparison.

**Settings.** `model_substitution_run`: paper victims (DeepSeek/Llama/GPT/Claude/
Gemini) → `deepseek/deepseek-v4-flash`; paper Model Judge (Gemini-2.5-Pro 3-judge
majority vote) → single goal-faithful Qi rubric on `deepseek/deepseek-v4-flash`.
Adaptive (Gemini-attacker-in-loop) optimization
deferred — closed-attacker policy; the static-template attack is the faithful
core. Some providers ignore assistant-prefill semantics; treat such targets as
capability checks, not method failures. Dataset: AdvBench (520) vendored at
`data/advbench_harmful_behaviors.csv`. Official source preserved under
`references/official/` (adaptive attacker + multi-judge majority vote kept as
provenance only). See `plan.md` for the full self-check.
