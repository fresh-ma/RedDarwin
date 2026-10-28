---
name: autodan-turbo
description: >
  AutoDAN-Turbo (arXiv:2410.05295, ICLR 2025) — black-box lifelong-agent jailbreak that
  self-explores, stores, retrieves, and recombines jailbreak STRATEGIES. All roles via
  OpenRouter (stdlib urllib). Use to run the faithful paper-local Code unit.
---

# AutoDAN-Turbo

Faithful black-box reproduction of **AutoDAN-Turbo** (SaFoLab-WISC/AutoDAN-Turbo).

## Modules

| file | role |
|------|------|
| `scripts/prompts.py` | Verbatim attacker / scorer / summarizer templates + dual yes/no judges |
| `scripts/models.py` | OpenAI-compatible client (`urllib`), walks up for `.env` to read `OPENROUTER_API_KEY` |
| `scripts/roles.py` | attacker / target / scorer / summarizer / dual judge + retrieval |
| `scripts/cases.py` | `data/harmful_behavior_requests.json` (warm_up=50, lifelong=400) |
| `scripts/attack.py` | thin CLI |

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`). API keys are read from the global `XSkillForge/.env`
(`scripts/models.py` walks up to find it) — no per-skill `.env`, no `uv run`,
no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Quick checks (offline, no API)

```bash
cd XSkillLib/Single-turn/Multi-Strategy-Pool/2410.05295_AutoDAN-Turbo/autodan-turbo
$PY scripts/attack.py --help
$PY scripts/attack.py --wiring-check
```

## Run (all roles over OpenRouter, key from global XSkillForge/.env)

```bash
cd XSkillLib/Single-turn/Multi-Strategy-Pool/2410.05295_AutoDAN-Turbo/autodan-turbo
$PY scripts/attack.py \
  --target api:deepseek/deepseek-v4-flash \
  --attacker api:deepseek/deepseek-v4-flash \
  --scorer api:deepseek/deepseek-v4-flash \
  --summarizer api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash \
  --sample 20 --epochs 4 --warmup-sample 6 --warmup-epochs 3 \
  --max-tokens 1024
```

## Dual metrics

- **refusal_bypass** / **content_harmful**: independent yes/no LLM judges (`--judge`).
- Paper in-loop **scorer** 1–10 (break ≥ 8.5) still drives the attack loop + reported as `paper_scorer_ge_break`.

## Dataset

Official `harmful_behavior_requests.json`: warm_up 50 + lifelong 400. Hold full set; sample for validation.

## Provenance

Official snapshot: `references/official/` (from SaFoLab-WISC/AutoDAN-Turbo).
Embedding: hashing bag-of-words substitutes OpenAI text-embedding-ada-002; retrieval selection logic is paper-faithful.
