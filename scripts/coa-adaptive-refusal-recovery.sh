#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/coa-adaptive-refusal-recovery"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM_SLUG="${VICTIM##*/}"
STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/coa-adaptive-refusal-recovery_${VICTIM_SLUG}_${N_GOALS}x.raw.json"
JUDGED_OUT="$RESULTS/coa-adaptive-refusal-recovery_${VICTIM_SLUG}_r5_${N_GOALS}x_${STAMP}.judged.json"

if [[ "${WIRING_CHECK:-0}" == "1" ]]; then
  "$PY" "$METHOD/scripts/attack.py" smoke --max-rounds 5 --out "$RAW_OUT"
  exit 0
fi

"$PY" "$METHOD/scripts/attack.py" run \
  --goals "$GOALS_FILE" \
  --target "api:$VICTIM" \
  --attacker api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash \
  --limit "$N_GOALS" --sample-rows "$N_GOALS" --max-rounds 5 --seed 20260626 \
  --target-max-tokens 2048 \
  --out "$RAW_OUT"

"$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_OUT"
