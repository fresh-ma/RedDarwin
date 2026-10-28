#!/usr/bin/env bash
# compound-roleplay (arXiv:2604.02652) attack on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv), strongest setting = full three-element combo (--elements all:
# persona + contrastive table + self_assessment; paper ASR 71.4% vs 14.3% for
# contrastive-only; local canonical run 20/20, see skill RESULT_2026-07-20.md),
# then unified judge. Only the judged file is kept in results/.
#
# No attacker role: the payload is composed statically (direct composition, no
# target/evaluator feedback loop); the CLI only has --target and --judge —
# --target follows $VICTIM, --judge stays api:deepseek/deepseek-v4-flash.
# Known risks: model substitution only (paper target was OpenAI gpt-oss-20b with
# human evaluators; here the judge is v4-flash via OpenRouter, judged again
# by unified_judge). No ablation is run — the canonical setting is the full combo.
# AdvBench's `request` column is accepted via a one-line loader patch in
# scripts/cases.py (goal|prompt|behavior|request); --sample $N_GOALS takes the
# first $N_GOALS rows of $GOALS_FILE in file order (no shuffle), guaranteeing
# the first $N_GOALS goals.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Persona-Roleplay/2604.02652_CompoundRoleplay/compound-roleplay"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t compound-roleplay_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/compound-roleplay_${VICTIM_SLUG}_all_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --elements all \
  --dataset "$GOALS_FILE" \
  --sample "$N_GOALS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
