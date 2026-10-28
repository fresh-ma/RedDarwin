---
name: actorbreaker
description: >
  Black-box multi-turn jailbreak (ActorBreaker / ActorAttack, Ren et al. ACL 2025,
  arXiv 2410.10700). Wraps a harmful target in a Latour Actor-Network, self-talks
  ≤5 benign-looking multi-turn queries per actor clue, then a summary turn
  recombines the victim's own answers into the harmful artifact. Judge = verbatim
  Qi-2023 GPT-4 1-5 harmfulness, success==score 5. Use to run/score this attack on
  an OpenRouter open/lab victim. Triggers: actorbreaker, actorattack, derail
  yourself, multi-turn actor-network jailbreak, 2410.10700.
---

# ActorBreaker (ActorAttack) — multi-turn actor-network jailbreak

Faithful paper-local reproduction of the black-box, prompt-layer attack from
arXiv 2410.10700 (official repo `AI45Lab/ActorAttack`). Two stages: pre-attack
(attacker LLM builds an actor-network and self-generates benign multi-turn query
chains) and in-attack (queries sent turn-by-turn to the victim, then a summary
turn consolidates). See `references/method.md` for the full mechanism and the
verbatim prompt provenance.

## Run

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/models.py` walks up from the method dir to find it) —
no per-skill `.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

```bash
cd XSkillLib/Multi-turn/Actor-Adaptive/2410.10700_ActorBreaker/actorbreaker
$PY scripts/attack.py \
  --target api:qwen/qwen-2.5-7b-instruct \
  --attacker api:deepseek/deepseek-chat \
  --judge api:deepseek/deepseek-v4-flash \
  --samples 20 --actors 3 --workers 20 --target-max-tokens 900
```

Writes `results/actorbreaker_<target>_<mode>_a<K>_<N>x_<stamp>.json` with the
standard result schema (`model_input_messages` + `model_output_text` per case)
and a dual-metric summary (`content_harmful` = fraction reaching judge score 5;
`refusal_bypass` proxy). Every metric is reported as `count/denominator = rate`.

## Modular roles (each a CLI flag; mix-and-match, `api:` | `ollama:`)
- `--target` victim model spec (default `api:deepseek/deepseek-v4-flash`; never GPT/Claude/Gemini).
- `--attacker` adversary LLM — pre-attack generation + dynamic-modify (default `api:deepseek/deepseek-chat`, fast/non-refusing).
- `--judge` Qi-2023 harmfulness judge serving model (default `api:deepseek/deepseek-v4-flash`, success == score 5).
- `--actors K` actor clues per behaviour (paper default 3).
- `--dynamic-modify` enable the optional rejective-rewrite module (default OFF; paper Table abla-DM: initial attack already high ASR).
- `--no-early-stop` judge every actor even after one scores 5.
- `--dataset` seed behaviours CSV (default `data/harmbench.csv`, 200 goals; also `data/circuit_breaker_train.csv`, 1000).
- `--target-max-tokens` victim response cap (default 900); `--reasoning-target` re-enables target thinking (default OFF for speed).

## Layout
- `scripts/attack.py` — thin orchestration + CLI (pre-attack → in-attack → summary → judge).
- `scripts/prompts.py` + `scripts/prompts/*.txt` — verbatim (byte-identical) official templates + Qi-2023 judge.
- `scripts/models.py` — OpenAI-compatible `ModelClient` (`api:`/`ollama:`) + walk-up `.env` loader (finds the global `XSkillForge/.env`).
- `scripts/roles.py` — `Attacker` / `Target` / `Judge` swappable adapters.
- `scripts/cases.py` — dataset DTO + loader. `data/` — full official datasets.
- `references/official/` — official source (provenance only).

## Notes
- Multi-turn → each case fires ~20–40 LLM calls; wall-clock ≈ slowest case chain.
  Use `--workers >= --samples` so cases run concurrently (one blocking run).
- Decode-then-judge not needed (no cipher); judge reads raw victim text verbatim.
- `payload_contract`: `not_composable` — the target-facing payload is a live
  adaptive dialogue (each turn depends on the victim's prior answer + optional
  attacker step-judge), not a freezable artifact. See `red_team_capability.json`.
