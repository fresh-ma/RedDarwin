# Runbook — MathPrompt (arXiv:2409.11445)

## What this is

Faithful black-box reproduction of MathPrompt: encode a natural-language harmful instruction as a
symbolic math problem (set theory + abstract algebra + symbolic logic) via an attacker LLM, prepend a
"solve then give a real-world example with real entities" instruction, send to the target LLM, and
judge with the HarmBench classifier. No GPU. See `../references/method.md` for mechanism
and verbatim-text provenance.

## Prerequisites

- `OPENROUTER_API_KEY` in nearest method-local or parent `.env` (auto-loaded; overrides stale shell value).
- `uv` (PEP-723 script; only dependency is `openai`).

## Reproduce

```bash
# target 1: qwen-2.5-7b
uv run python scripts/attack.py --target api:qwen/qwen-2.5-7b-instruct --sample 20 --max-tokens 1024

# target 2: mistral-nemo
uv run python scripts/attack.py --target api:mistralai/mistral-nemo --sample 20 --max-tokens 1024
```

Each run: 20 AdvBench behaviors x {direct, mathprompt} = 40 question-runs, ~80-105s, 0 errors.
Stage 1 encodes the 20 math problems once (concurrent); stage 2 runs target + HarmBench judge
(concurrent). Output → `results/mathprompt_<target>.json` with full per-case inspectable I/O.

## Settings (>=2 parameter sets)

- `direct` — raw harmful behavior sent to the target (the paper's ~1% baseline).
- `mathprompt` — the attack: prepended solver instruction + symbolic-math-encoded behavior.

## Results (real runs, 2026-06-11)

| target | setting | content_harmful | refusal_bypass |
|---|---|---|---|
| qwen-2.5-7b | direct | 0.000 | 0.000 |
| qwen-2.5-7b | mathprompt | 0.250 | 1.000 |
| mistral-nemo | direct | 0.050 | 0.150 |
| mistral-nemo | mathprompt | 0.200 | 1.000 |

Headline: symbolic-math encoding bypasses refusal entirely (0 → 1.0) on both targets — the paper's
central claim. content_harmful below the paper's 73.6% (weaker substitute attacker/judge + small open
targets); documented in `method.md` / `check.json`.

## Judge note

The paper's evaluator is the GPU-only `cais/HarmBench-Llama-2-13b-cls`. Its **standard classifier
prompt is embedded verbatim** (`HARMBENCH_CLS_PROMPT`) and served on `deepseek/deepseek-chat`
(OpenRouter) — a documented judge-model substitution (`code_knowledge/logistics.md`). To run the
*actual* HarmBench classifier weights instead, use the `safety-judge` skill on Deakin
(`run_judge.py --judge harmbench`) over the saved `model_output_text` fields.

## Knobs

`--target --attacker --judge --settings --sample --max-tokens --workers --dataset --out`. Targets are
open/lab OpenRouter models only — never GPT/Claude/Gemini.
