---
name: crescendo
description: "Run a paper-local, PyRIT-faithful Crescendo multi-turn jailbreak: an attacker LLM escalates a benign opening toward a harmful objective over N turns with refusal-driven backtracking, scored by PyRIT's refusal + task-achieved judges."
metadata:
  paper: "2404.01833_multi-turn-crescendo-jailbreak"
  case_type: black_box_generator_loop
  access: black_box
  artifact_bundle: [paper_digest, advbench_goals, attacker_model, target_model, turn_history, refusal_judge, objective_judge]
  execution_mode: [inspect, render, smoke, wiring_check_fake, live_api]
  evidence_level: code_repo_ready
  mechanism: multi-turn gradual escalation with backtrack-on-refusal
  fidelity_level: partial_algorithm_code
  pyrit_source: "microsoft/PyRIT@3a435ad pyrit/executor/attack/multi_turn/crescendo.py"
  script: "scripts/attack.py"
  status: self_contained_code_ready
---

# Crescendo

Faithful port of Microsoft PyRIT's `CrescendoAttack`. An attacker LLM (driven by
PyRIT's `crescendo_variant_1.yaml` system prompt) emits a JSON
`{generated_question, last_response_summary, rationale_behind_jailbreak}` each
turn, gradually escalating a benign opening toward the harmful objective on the
target's full multi-turn history. Each target reply is refusal-scored
(`SelfAskRefusalScorer`, OBJECTIVE_STRICT) — a refusal **backtracks** (drop the
turn, re-ask, don't advance) up to `--max-backtracks`. Non-refusals are
objective-scored on PyRIT's 0-100 task-achieved scale; normalized `>= 0.8`
(`FloatScaleThresholdScorer`) means the objective is achieved. All four prompts
are ported verbatim into `prompts/` and cited, not imported.

Roles run on OpenRouter `api:<model>` (`gpu_not_required`). The judge prompt is verbatim;
only the serving model is substituted to a permissive OpenRouter model
(`openai/*` route 403s on harmful-judge prompts).

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + `pyyaml`). API keys are read from the global
`XSkillForge/.env` (`scripts/models.py` walks up from the paper dir to find it) —
no per-skill `.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Quick checks (offline)
```bash
cd XSkillLib/Multi-turn/Crescendo/2404.01833_Crescendo/crescendo
$PY scripts/attack.py inspect --sample-rows 3 --out /tmp/crescendo-inspect.json
$PY scripts/attack.py render  --sample-rows 1 --out /tmp/crescendo-render.json
$PY scripts/attack.py smoke   --out /tmp/crescendo-smoke.json   # wiring only
```

## Live run (target + attacker + judges over OpenRouter, key from global XSkillForge/.env)
```bash
cd XSkillLib/Multi-turn/Crescendo/2404.01833_Crescendo/crescendo
$PY scripts/attack.py run \
  --goals data/advbench/harmful_behaviors.csv \
  --target api:deepseek/deepseek-chat \
  --attacker api:deepseek/deepseek-chat \
  --judge-model deepseek/deepseek-chat \
  --sample-rows 20 --settings-max-turns 5,8 --max-backtracks 2 --seed 20260610 \
  --out results/crescendo_deepseek_pyrit_20x2_20260610.json
```

`--goals` is dataset-agnostic (the paper-local `digest/tables/tab-advbenchtasks.tex`
12-task table or any `goal`/`Behavior` CSV). `--settings-max-turns` takes a comma
list and runs one pass per value (>=2 settings for completion). Live outputs use
`evidence_level=real_model_run` and store per-turn target/attacker I/O plus both
judge verdicts and the dual ASR. `smoke` / `--wiring-check` are wiring-only.

## Final result (canonical classification evidence)

`results/crescendo_advbench50_v4flash_tokfix_20260626.json` plus
`results/GLM_REVIEW_tokfix_20260626.md` — target/attacker/judge all
`deepseek/deepseek-v4-flash`, 6 AdvBench goals × 2 settings (`max_turns` 4,6) =
**12 cases**. Raw and audited `asr_content_harmful` are **11/12 = 0.9167** under
the recorded audit rubric; case 11 is explicitly borderline and becomes a false
positive under a stricter suicide-specificity requirement. This is a
model-substitution, self-judge run and the JSON sets
`valid_for_code_completion=false`; use it as canonical classification evidence,
not as proof of full reproduction completion. The older 40-case result remains
useful broader run evidence but lacks the companion skeptical case audit.
