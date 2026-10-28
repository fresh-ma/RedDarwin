#!/usr/bin/env bash
# LASH (adaptive semantic hybridization, 2605.21362) on $VICTIM
# (default qwen/qwen3.7-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/AdvBench.csv, N_GOALS default 5), then unified judge.
# Only the judged file is kept in results/.
#
# Setting basis: the skill's documented canonical live run
# (results/lash_v4flash_n10_fixed_20260628.json) = paper GA defaults
# (P=8, G=2, sigma=0.6, tau=9, seed budgets 5/5/10) with the GA target-query
# budget reduced to 50 for run-time (--max-target-queries 50); reproduced here.
#
# Known risks:
# - This skill talks to OpenRouter directly with BARE model ids (no api: prefix).
# - All four roles are forced to deepseek/deepseek-v4-flash per project
#   convention, but SKILL.md designed judge/composition/attacker as cheap
#   NON-reasoning models (qwen-2.5-7b / mythomax). v4-flash is a reasoning
#   model: the judge fires once per GA candidate and a "max_tokens too low"
#   error there is NOT caught by the GA loop (would abort the run), so
#   --judge-max-tokens is raised to 4096; --attacker-max-tokens raised to 2048
#   (attacker failure only falls back to templated seeds; composition failure
#   is caught and error-skipped, canonical run had 1 such truncation).
# - v4-flash as seed attacker may refuse to write adversarial seeds -> weak
#   templated fallback seeds (mechanism intact, ASR may drop vs mythomax).
# - scripts/attack.py read_dataset() was patched to also accept a `request`
#   column so bench/AdvBench.csv (request,target) loads directly.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Multi-Strategy-Pool/2605.21362_LASH/lash"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t lash_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/lash_${VICTIM_SLUG}_ga-q50_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
#    --sample "$N_GOALS" takes the first N_GOALS rows; no shuffle in this skill's loader.
cd "$METHOD"
"$PY" scripts/attack.py \
  --target-model "$VICTIM" \
  --judge-model deepseek/deepseek-v4-flash \
  --attacker-model deepseek/deepseek-v4-flash \
  --composition-model deepseek/deepseek-v4-flash \
  --judge-max-tokens 4096 --attacker-max-tokens 2048 \
  --dataset "$GOALS_FILE" \
  --sample "$N_GOALS" --max-target-queries 50 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
