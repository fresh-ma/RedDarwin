#!/usr/bin/env bash
# GPTFuzzer 2.0 — feedback-directed (frame, transform) fuzzing.
# Reads VICTIM, GOALS_FILE, N_GOALS; writes one unified judged *.judged.json
# per run into ATTACK_RESULTS_DIR. Per-goal checkpoints live in
# ATTACK_RESULTS_DIR/checkpoints/ so an interrupted run resumes safely.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/gptfuzzer-2-0"

VICTIM="${VICTIM:-qwen/qwen3.7-flash}"
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/gptfuzzer-2-0-$(date +%Y%m%d-%H%M%S)}"
MAX_CALLS_PER_GOAL="${MAX_CALLS_PER_GOAL:-6}"
RESUME="${RESUME:-0}"

xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"

export PYTHONUNBUFFERED=1
mkdir -p "$ATTACK_RESULTS_DIR"
VICTIM_SLUG="${VICTIM##*/}"
STAMP="$(date +%Y%m%d-%H%M%S)"
JUDGED_OUT="$ATTACK_RESULTS_DIR/gptfuzzer-2-0_${VICTIM_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

RESUME_ARGS=()
if [[ "$RESUME" == "1" ]]; then
  RESUME_ARGS=(--resume)
fi

# Run the feedback-directed fuzzing attack (per-goal checkpoints).
"$PY" "$METHOD/run.py" \
  --victim "$VICTIM" \
  --goals "$GOALS_FILE" \
  --n-goals "$N_GOALS" \
  --results-dir "$ATTACK_RESULTS_DIR" \
  --judge-model api:deepseek/deepseek-v4-flash \
  --max-calls-per-goal "$MAX_CALLS_PER_GOAL" \
  --seed 42 \
  --sleep 0.2 \
  ${RESUME_ARGS[@]+"${RESUME_ARGS[@]}"} \
  --timeout 180

# Find the raw result that was just produced.
RAW_OUT="$(ls -t "$ATTACK_RESULTS_DIR"/gptfuzzer-2-0_*.json | grep -v '\.judged\.json$' | head -n1)"

# Unified judge re-score.
"$PY" "$ROOT/judge/unified_judge.py" \
  --input "$RAW_OUT" \
  --output "$JUDGED_OUT" \
  --model api:deepseek/deepseek-v4-flash
