---
name: bijection-learning
metadata:
  paper: "2410.01294_bijection-based-llm-jailbreak"
  fidelity_level: paper_algorithm_code
  access: black_box
  mechanism: in-context bijection encoding jailbreak
  script: "scripts/attack.py"
description: >
  Bijection-learning jailbreak (arXiv:2410.01294, "Endless Jailbreaks with Bijection Learning").
  Sample a RANDOM alphabet->string bijection (permuted letters or l-digit numbers), TEACH it to the
  target in-context (system mapping + English<->"Language Alpha" teaching turns), then send the
  harmful query ENCODED in the bijection plus an affirmative prefill; decode the reply and judge it.
  Random + endless => best-of-n fuzzing (pass@n). Judge = HarmBench classifier prompt (verbatim) on
  the DECODED text. Black-box, temperature 0, no GPU. Use to test cipher/in-context-learning jailbreaks.
---

# Bijection Learning (encoding + in-context-learning jailbreak)

Faithful reproduction of arXiv:2410.01294, ported from the official repo
`haizelabs/bijection-learning`. Black-box, multi-turn teaching prompt, temperature 0, no GPU.
Mechanism + line-by-line provenance in `references/method.md`.

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, dep `openai`). API keys are read from the global `XSkillForge/.env`
(`scripts/attack.py` walks up from its own location to find it) — no per-skill `.env`,
no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Run

```bash
cd XSkillLib/Single-turn/Encoding-Linguistic/2410.01294_BijectionLearning/bijection-learning

# CAPABLE-TARGET demonstration: qwen-2.5-72b — the "bijection works" case (not a reasoning model,
# so max_tokens 1536 yields 0 empties here).
$PY scripts/attack.py run \
  --target qwen/qwen-2.5-72b-instruct --judge deepseek/deepseek-v4-flash \
  --settings direct,bijection --bijection-type letter --fixed-size 18 \
  --num-teaching-shots 5 --max-message-length 240 --prefill --trials 4 --sample 20 --workers 16 \
  --max-tokens 1536 \
  --out results/bijection_qwen72b_demo_<DATE>.json

# CAPABILITY-GATE comparison: mid-size v4-flash engages the cipher but cannot sustain it (scores 0.0)
# NOTE: v4-flash is a REASONING model — low max_tokens makes it spend the budget on hidden reasoning
# and emit EMPTY content. Use --max-tokens 16384 so the canonical has 0 status=ok-but-empty cells.
$PY scripts/attack.py run \
  --target deepseek/deepseek-v4-flash --judge deepseek/deepseek-v4-flash \
  --settings direct,bijection --bijection-type letter --fixed-size 18 \
  --num-teaching-shots 5 --max-message-length 240 --prefill --trials 4 --sample 20 --workers 16 \
  --max-tokens 16384 \
  --out results/bijection_letter_v4flash_20x_mt16384_<DATE>.json

# Earlier small-open-target run: qwen-2.5-7b, 20 behaviors, best-of-4
$PY scripts/attack.py \
  --target qwen/qwen-2.5-7b-instruct --sample 20 --trials 4 --max-tokens 800
```

Targets must be **open/lab** models on OpenRouter (NEVER GPT/Claude/Gemini — ban risk + 403).
`OPENROUTER_API_KEY` auto-loads from the global `XSkillForge/.env` (walk-up from the script).

## How to swap parameters (rubric §1 — every experiment-meaningful knob is tunable)

- **Swap the target model**: change `--target` to any open/lab OpenRouter chat id
  (e.g. `qwen/qwen-2.5-72b-instruct`, `deepseek/deepseek-v4-flash`, `mistralai/mistral-nemo`,
  `qwen/qwen-2.5-7b-instruct`). Bijection is capability-gated — pick a model large enough to hold the
  cipher (≥70B-class) to reproduce success, or a mid-size model to demonstrate the cipher-capacity
  cliff (0.0 ASR).
- **Swap the judge/evaluator**: change `--judge` (default `deepseek/deepseek-chat`). The verbatim
  HarmBench classifier prompt is served on whatever OpenRouter model you name. The paper's official
  judge is GPT-4o-mini on this prompt (the GPU classifier is `cais/HarmBench-Llama-2-13b-cls`).
- **Swap the bijection type**: `--bijection-type letter` (permuted alphabet, default) or
  `--bijection-type digit` (random ℓ-digit numbers per letter, paper Sec 2.1). For digit mode also
  set `--num-digits` (default 2 = ℓ) and optionally `--delimiter` (default `"  "`).
- **Swap the difficulty (dispersion)**: change `--fixed-size`. **dispersion d = 26 − fixed_size**;
  smaller `--fixed-size` ⇒ harder bijection (more letters permuted), suited to stronger models;
  larger `--fixed-size` ⇒ easier, suited to smaller models. Paper default sweep is `fixed_size` ∈
  {18, 13, 8} → d ∈ {8, 13, 18}. Default 18 (d=8) matches the paper's small-model guidance.
- **Swap the best-of-n budget**: change `--trials` (default 4) — `bijection` ASR is collapsed
  pass@n across independently sampled bijection maps per behavior.
- **Swap the teaching-shot count**: change `--num-teaching-shots` (k_t, default 5; paper uses 5).
- **Swap the dataset**: change `--dataset` to any harmful-behaviors CSV with a `goal` (or
  `Behavior`) column. Default is the cached AdvBench 520 (`data/harmful_behaviors.csv`);
  the paper also ships the official AdvBench-50 (the official AdvBench-50 (haizelabs/bijection-learning datasets/advbench_behaviors.csv)) and
  HarmBench test (HarmBench test (haizelabs/bijection-learning datasets/harmbench_behaviors_text_test.csv)).
- **Swap the output path**: change `--out`. Default writes to `results/bijection_<type>_<target>.json`.
- **Disable prefill**: pass `--no-prefill` to drop the affirmative assistant prefill (paper Sec 2).
- **Reproducibility**: each (behavior, trial) seeds its own `random.Random` from `--seed`, so reruns
  are deterministic for the same `--seed`; only OpenRouter-side nondeterminism can shift pass@n hits.

## Flags

- `--target` OpenRouter target id (with/without `api:` prefix)
- `--judge` model serving the verbatim HarmBench classifier prompt (default `deepseek/deepseek-chat`)
- `--settings direct,bijection` the ≥2 parameter sets (raw baseline vs the attack)
- `--bijection-type letter|digit` codomain: permuted alphabet or random l-digit numbers (paper Sec 2.1)
- `--fixed-size` letters mapped to themselves; **dispersion = 26 − fixed_size** (the difficulty knob).
  Smaller models need *lower* dispersion (higher `--fixed-size`, default 18); stronger models tolerate
  higher dispersion — the paper's "stronger with scale" axis.
- `--num-digits` digits per token for `digit` type (default 2 = ℓ)
- `--num-teaching-shots` k_t teaching turns (default 5); `--max-message-length` char cap per essay
- `--prefill / --no-prefill` affirmative assistant prefill (default on)
- `--trials` best-of-n attack budget (pass@n; default 4)
- `--sample` number of harmful behaviors (AdvBench `goal` column); `--max-tokens`, `--workers`, `--seed`
- `--dataset` / `--out` overrides

## Output

`bijection-learning/results/bijection_<type>_<target>.json` (current run) and
`results/bijection_<type>_<target>.json` (prior runs) — per-(behavior,trial) inspectable I/O (the
sampled bijection map, the raw Language-Alpha output, the decoded English, the HarmBench label) +
per-setting dual-metric summary. `bijection` ASR is collapsed pass@n across trials per behavior.

## Headline (CANONICAL — dual target, GLM-audited, 0 errors)

Same attack (letter bijection, `k_t=5`, `fixed_size=18`, `--prefill`, pass@4, 20 AdvBench behaviors,
target max_tokens 1536, temp 0, HarmBench classifier judge on the DECODED text) on two targets:

| target | setting | refusal_bypass | raw content_harmful | **GLM-audited** |
|---|---|---|---|---|
| **qwen-2.5-72b** (capable) | bijection | 1.000 | 0.200 | **0.100 (2/20)** |
| qwen-2.5-72b              | direct   | 0.200 | 0.000 | 0.000 |
| **deepseek-v4-flash** (mid-size 2026) | bijection | 1.000 | 0.000 | **0.000 (0/20)** |
| deepseek-v4-flash                     | direct   | 0.000 | 0.000 | 0.000 |

Audits: `results/GLM_REVIEW_qwen72b_20260627.md` (qwen-72b: 2/4 HarmBench hits confirmed — a
working SQL-injection exploit script + a six-step identity-theft procedure; 2 false-pos) and
`results/GLM_REVIEW_20260626.md` (v4-flash: 0/4 *missed* — 0.0 is genuine, reverse-audited).
Source runs: `results/bijection_qwen72b_demo_20260627.json` + `results/bijection_letter_v4flash_20x_mt16384_20260628.json`
(v4-flash rerun at max_tokens 16384: 0 status=ok-but-empty; earlier mt1536/mt8192 runs with empties archived in `results/_process/`).

### Key finding: bijection is CAPABILITY-GATED (inverts "weaker = more vulnerable")

Both targets accept the cipher game (refusal_bypass = 1.0 — they always reply in Language Alpha).
But only the **larger qwen-2.5-72b can SUSTAIN an 18-symbol bijection well enough to emit coherent
harmful output**; the mid-size 2026 deepseek-v4-flash cannot — it produces refusals-in-cipher,
garbled high-char-error-rate decodes, and bait-and-switch. This matches the paper's "stronger with
scale" thesis (~80% on frontier Claude-3.5-Sonnet): bijection needs a SMART victim. So v4-flash's
0.0 is a real robustness boundary (insufficient cipher capacity), not an attack failure. Headline
evidence the mechanism works lives in `bijection_qwen72b_demo_20260627.json`.

### Earlier small-open-target runs (letter, dispersion 8, best-of-4)

| target | direct content_harmful | bijection content_harmful | direct refusal_bypass | bijection refusal_bypass |
|---|---|---|---|---|
| qwen-2.5-7b  | 0.050 | **0.750** | 0.000 | **1.000** |
| mistral-nemo | 0.200 | **0.450** | 0.300 | **1.000** |

Smaller open models are easier to push to *content*-harmful at dispersion 8 but cannot reach the
paper's frontier-model peak (86% on Claude 3.5 Sonnet). We report the pre-human-PREFS-filter
LLM-judge ASR (paper Appendix 11 reports these too). Honest delta in `references/method.md` + `plan.md`.

### Earlier v4-flash d-sweep (12 behaviors × pass@8, target = judge)

| config | n | content_harmful ASR | refusal_bypass ASR |
|---|---|---|---|
| direct (baseline)     | 12 | 0.000 | 0.000 |
| bijection letter d=8  | 12 | 0.167 | 1.000 |
| bijection letter d=13 | 12 | 0.083 | 1.000 (prior run) |

Raising dispersion 8→13 did not raise ASR on v4-flash (smaller model → lower dispersion is the
paper's guidance). Pass@8 over random bijections is mildly nondeterministic across OpenRouter
reruns; the d=8 0.167 line is the larger pass-budget run. See `RESULT_2026-06-26.md`.
