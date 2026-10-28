# plan — ReNeLLM (2311.08268) reproduction (plan-first gate record)

Agreed with Oscar via the stage-1 verify gate (2026-06-25). Reproduce ReNeLLM as a
black-box LLM-assisted prompt attack; reuse the faithful `scripts/attack.py` (6 rewrite
ops / 3 scenarios / official binary judge / TEST_PREFIXES gate / scenario nesting — verbatim
from `NJUNLP/ReNeLLM`).

## Locked decisions
- **Classification / bucket**: stays **black-box**; carries the `llm-assisted-prompt-attack`
  taxonomy label (LLM-assisted prompt optimization, model-agnostic). Not the pure
  prompt-template bucket. (don't fully re-bucket until promote.)
- **Models**: target = judge = `deepseek/deepseek-v4-flash` (OpenRouter), `model_substitution_run`
  (paper used GPT-3.5/4 + Claude + Llama2). Attacker/rewrite model is a CLI knob.
- **Scale**: T=10 (CLI param), 10 rows × 3 scenarios = 30 cases per config, dual-metric judge.
- **Evidence**: fresh v4-flash run (not reuse of the old deepseek-chat run).

## Runs delivered (results/)
- **Faithful** (attacker = v4-flash): ASR_content_harmful **0.23** (7/30). 23/30 failed at the
  attacker-rewrite stage because v4-flash refuses to rewrite harmful goals — an expected
  model-assistant phenomenon, counted as failure (faithful). Crush field-by-field verified:
  no false positives.
- **Non-refusing attacker** (attacker = mythomax-13b, cheap non-refusing): ASR recovers to
  **~0.8** (text_continuation 0.8), confirming attacker-refusal was the bottleneck, not weak
  attack. See `results/RESULT_2026-06-25.md`.

## Key finding → code change
Attacker-LLM refusal handling added to `attack.py`: `--rewrite-fallback-model` + short-circuit
on empty/prefix-refusal rewrites (reuses `has_refusal_prefix`). Don't over-engineer; count
rare residual refusals as failure. Verified non-refusing attacker panel:
`tools/openrouter_fallback/models.json → rewrite_attacker_models` (default mythomax-13b).

## Run
See `SKILL.md` § Run. One command per scenario; all params are CLI flags.
