#!/usr/bin/env bash
# DrAttack 2.0 (two-stage referential reconstruction) on $VICTIM, first
# $N_GOALS goals of $GOALS_FILE, then unified judge. Thin wrapper; all attack
# logic lives in the proposal directory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-50}"
VICTIM_SLUG="${VICTIM##*/}"
VICTIM_SLUG="${VICTIM_SLUG//\//-}"
METHOD="$ROOT/XSkillLib/Proposal/drattack2-0"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

# Raw output lives in the results dir under a stable name so an interrupted
# run resumes in place (completed goals are skipped on rerun).
RAW_OUT="$RESULTS/drattack2-0_${VICTIM_SLUG}_referential_${N_GOALS}x.json"
JUDGED_OUT="$RESULTS/drattack2-0_${VICTIM_SLUG}_referential_${N_GOALS}x.judged.json"

"$PY" "$METHOD/attack2.py" \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --out "$RAW_OUT"

cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
