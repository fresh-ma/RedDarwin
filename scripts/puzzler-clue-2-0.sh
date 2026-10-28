#!/usr/bin/env bash
# Puzzler Clue 2.0 (proposal puzzler-clue-2-0) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv, first 5). One shared clue set per goal (Phases 1-2 of the
# parent Puzzler pipeline), then one target call using the globally selected
# best variant: coded-clues. This paper-run wrapper intentionally fixes that
# choice so an inherited environment variable cannot mix in an ablation.
# Only the judged file is kept in results/.
#
# Notes:
#   - target params follow the parent's strongest canonical setting (setB:
#     temperature 0.7) with max-tokens 32768 — the coded variants' mechanical
#     decode needs the headroom, and reasoning victims burn hidden tokens
#     (parent published run: 2 empty gpt-oss outputs at 2048; proposal probe 2:
#     deepseek empty completions on the decode task persisted at 16384; the
#     provider allows up to 384k completion tokens).
#   - the raw output path is stable per (victim, N_GOALS, variants, results
#     dir) so a retried wrapper resumes the runner's per-case checkpoint
#     (including memoized clue sets) instead of re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/puzzler-clue-2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VARIANTS="coded-clues"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
VARIANT_SLUG="${VARIANTS//,/+}"
RAW_OUT="$RESULTS/puzzler-clue-2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/puzzler-clue-2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --variants "$VARIANTS" \
  --temperature 0.7 --attack-temperature 1.0 \
  --max-tokens 32768 --max-defensive 10 \
  --workers 5 --goal-workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
