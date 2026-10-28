#!/usr/bin/env bash
# RACE attack on $VICTIM, first $N_GOALS goals of $GOALS_FILE,
# strongest setting (Config B: 5 turns, 3 seeds), then unified judge.
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Multi-turn/Actor-Adaptive/2502.11054_RACE/race"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
TAG="advbench${N_GOALS}_${XSF_JOB_ID:-$STAMP}"
RAW_OUT="$METHOD/results/race_${TAG}_t5_s3_n${N_GOALS}.json"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/race_${VICTIM_SLUG}_t5s3_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/race_attack.py \
  --victim "api:$VICTIM" \
  --shadow api:deepseek/deepseek-v4-flash \
  --judge  api:deepseek/deepseek-v4-flash \
  --data "$GOALS_FILE" \
  --sample "$N_GOALS" --turns 5 --seeds 3 \
  --victim-max-tokens 900 --tag "$TAG"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
