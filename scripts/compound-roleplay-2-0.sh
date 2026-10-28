#!/usr/bin/env bash
# compound-roleplay-2-0 (proposal compound-roleplay-2-0) on $VICTIM (default
# deepseek/deepseek-v4-flash-0731), first $N_GOALS goals of $GOALS_FILE
# (default bench/advbench_50.csv). One auxiliary-LLM veil per goal
# (deepseek/deepseek-v4-flash, fallback deepseek/deepseek-v4-flash; memoized by goal text in the
# checkpoint), then ONE victim call per goal over the frozen single variant
# (veiled case-file reconstruction), then the unified judge. Only the judged
# file is kept in results/.
#
# Notes:
#   - the evaluator invokes this wrapper once per goal (N_GOALS=1) with up to
#     80 concurrent processes; the raw output path is stable per
#     (victim, N_GOALS, results dir) so a retried invocation resumes the
#     runner's per-case checkpoint (including memoized veils) instead of
#     re-paying calls, and the judged filename carries a stamp so concurrent
#     runs never collide.
#   - API keys load from $ROOT/.env via the runner's walk-up loader.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/compound-roleplay-2-0"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash-0731}"   # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/compound-roleplay-2-0_${VICTIM_SLUG}_all_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/compound-roleplay-2-0_${VICTIM_SLUG}_all_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack
"$PY" "$METHOD/scripts/attack.py" \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --dataset "$GOALS_FILE" \
  --sample "$N_GOALS" \
  --goal-workers 4 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
