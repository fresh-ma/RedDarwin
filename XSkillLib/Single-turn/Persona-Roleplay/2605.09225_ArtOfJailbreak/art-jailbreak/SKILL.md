---
name: art-jailbreak
description: ART / OPTIMUS compositional jailbreak (arXiv 2605.09225). Black-box, single-turn. Compose(q, s) applies in-the-wild jailbreaking tactics to a simple harmful seed, queries a target, and scores with the paper's OPTIMUS J(S,H) metric + a dual refusal-bypass / content-harmful judge. Faithful-from-paper (only released code is the optimus-jbscorer SCORER, reproduced byte-identically).
---

# ART / OPTIMUS compositional jailbreak (2605.09225)

## What

"The Art of the Jailbreak" formulates jailbreaks as **compositional generation**: a *simple harmful
prompt* `q` is combined with in-the-wild (ITW) jailbreaking **tactics** `s` to produce a jailbreak
prompt `j = Compose(q, s)` that **preserves the malicious intent while reducing surface-level
detectability**. The paper mines `N=912` tactics from WildJailbreak and composes them with `M=125`
JailBreakV-28K seeds into a 114,912-prompt grid, then scores every prompt with **OPTIMUS** — a
continuous 2-D metric `J(S, H)` over semantic similarity `S` and harmfulness `H` — instead of a
binary ASR. This unit reimplements the **attack** (black-box, single-turn) and reproduces the
OPTIMUS scorer.

- **fidelity_level**: `faithful_from_paper`. The only released code is `optimus-jbscorer` (the
  SCORER, not the attack). `roles.jbscore` is a byte-identical scalar port of its `jbscore` formula
  (verified: `J(0.57, 0.43) = 0.471`, matching the paper's theoretical optimum `J_max ≈ 0.47`).
- **Verbatim** (from the paper/artifact): the Listing-1 refusal list, the Listing-2 WildTeaming
  tactic-extraction prompt, the Listing-3 OPTIMUS Likert rubric, the OPTIMUS J(S,H) formula.
- **Reconstructed** (paper's source is empty): the `Compose(q, s)` operator prompt — see
  `scripts/prompts.py` header. This is the one non-verbatim template.

## Use

Threat model: **black-box**, text chat input, single-turn. Every model role is a swappable flag,
default `api:deepseek/deepseek-v4-flash`:

- `--composer`     — the `Compose(q, s)` generator LLM
- `--target`       — the victim model
- `--optimus-judge`— the OPTIMUS S/H Likert-rubric LLM (paper's own metric)
- `--judge`        — the content-harmful response judge (`proxy` / `none` for refusal-only)

Scoring axes: **OPTIMUS J(S,H)** on the `(q, j)` prompt pair (+ 4-level band safe_fail / weak /
moderate / optimal) AND a **dual metric** on the response (refusal-bypass via Listing-1 keywords +
content-harmful via LLM judge).

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + `numpy` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/models.py` walks up through every ancestor directory to find it) —
no per-skill `.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Run

```bash
cd XSkillLib/Single-turn/Persona-Roleplay/2605.09225_ArtOfJailbreak/art-jailbreak

# static wiring check — no API, fake models
$PY scripts/attack.py smoke --sample-rows 2

# preview one composed jailbreak prompt (calls composer only; use --composer fake for offline)
$PY scripts/attack.py render --num-strategies 3 --seed 1 --composer fake

# real black-box run (≥10 cases, deepseek target/composer/judges)
$PY scripts/attack.py run --sample-rows 10 --num-strategies 3

# mix-and-match roles + fixed tactic combo
$PY scripts/attack.py run --sample-rows 10 \
  --composer api:mistralai/mistral-nemo \
  --target api:qwen/qwen-2.5-7b-instruct \
  --strategy-mode fixed --strategy-names "Contextualization the task,Roleplay,Seed-leading sentence"

# rebuild the tactic pool from a jailbreak corpus (verbatim WildTeaming extraction prompt)
$PY scripts/attack.py extract --pairs <pairs.csv>   # columns: simple_prompt,jailbreak_prompt
```

Results land in `results/art_{target}_{mode}s{k}_{N}x_{YYYYMMDD-HHMMSS}.json` with per-case records
(strategies, jailbreak_prompt, target_response, optimus {S,H,J,band}, dual {refusal_bypass,
content_harmful}) and a counts-format summary.

## Test

- `$PY -m py_compile scripts/*.py`
- `$PY scripts/attack.py --help` / `smoke` / `render --composer fake` — no API.
- jbscore parity: `J(0.57,0.43)=0.471` ≈ paper `J_max`.

## Settings

- **Optional real OPTIMUS scorer** (GPU/HF): `--optimus-backend local` uses the released SBERT
  all-mpnet-base-v2 (S) + DeBERTa-large-MNLI (H) models. Needs `torch` + `sentence-transformers` +
  `transformers` in the shared venv (already installed there).
  The default `llm` backend keeps the whole pipeline black-box (no GPU).
- **Dataset**: `data/seeds.csv` (25 AdvBench-style seeds tagged with the paper's cyber-attack
  taxonomy) substitutes for gated JailBreakV-28K; `--data` swaps in any `goal[,category]` set.
  `data/strategies.json` (24 ITW tactics) substitutes for gated WildJailbreak. See `data/README.md`.
- **Reasoning off** on target by default (jailbreak eval judges only the final answer).
