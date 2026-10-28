#!/usr/bin/env bash
# CognitiveBreak (proposal cognitivebreak) on $VICTIM, first $N_GOALS goals of
# $GOALS_FILE (default bench/AdvBench.csv, first 5). Fusion of
# cognitive-overload-2-0 (encoded veil memo + decode) and breakme2-0
# (victim-self-generation + judge-in-the-loop refusal-aware search): one
# encoded seed, then best-first expansion with a hard 40 victim-call cap per
# goal, then the unified judge. Only the judged file is kept in results/.
#
# Notes:
#   - victim params: temperature 0.7, max-tokens 32768 (decode load needs
#     headroom; parents found 16384 truncates reasoning victims), timeout 120.
#   - aux roles (veil, internal judge, JSON fixer): deepseek/deepseek-v4-flash with a
#     per-call deepseek/deepseek-v4-flash fallback, inside the runner (AGENTS.md rule).
#   - the raw output path is stable per (victim, N_GOALS, results dir) so a
#     retried wrapper resumes the runner's checkpoint (memoized veils,
#     completed cases, mid-case state) instead of re-paying calls.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/cognitivebreak"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
MAX_QUERIES="${MAX_QUERIES:-8}"   # hard victim-call cap/goal (budget allows up to 40; 8 keeps worst-case deepseek shards under the 1800s harness timeout)
POOL_SIZE="${POOL_SIZE:-8}"
VARIANT="${VARIANT:-fused}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/cognitivebreak_${VICTIM_SLUG}_${VARIANT}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/cognitivebreak_${VICTIM_SLUG}_${VARIANT}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --max-queries "$MAX_QUERIES" --pool-size "$POOL_SIZE" \
  --temperature 0.7 \
  --max-tokens 32768 --timeout 120 \
  --case-workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
