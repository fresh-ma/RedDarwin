#!/usr/bin/env bash
# Stochastic Monkeys 2.0 — semantic best-of-n jailbreak wrapper.
# Runs the first $N_GOALS rows of $GOALS_FILE against $VICTIM, then applies the
# unified judge.  All attack logic lives in the proposal directory; this script
# is only a thin adapter for the forge harness.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash-0731}"
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Proposal/stochastic-monkeys2-0"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t sm2-0_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/stochastic-monkeys2-0_${VICTIM_SLUG}_semantic_k12_${N_GOALS}x_${STAMP}.judged.json"

# Frozen global variant defaults: semantic composition, k=12, gamma=0.
cd "$METHOD"
"$PY" attack.py run \
  --dataset "$GOALS_FILE" \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --variant semantic \
  -k 12 --gamma 0.0 --p-noise 0.03 \
  --sample "$N_GOALS" --workers 5 \
  --out "$RAW_OUT"

cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
