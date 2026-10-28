#!/usr/bin/env bash
# Storyboard Continuity Engrossment, incomplete-source repair
# (proposal storyboard-continuity) on $VICTIM, first $N_GOALS goals of
# $GOALS_FILE. One auxiliary compiler call per goal (incomplete continuity
# brief: short objective + 3-6 shot seeds with bounded fragments and open
# questions, fixed deepseek/deepseek-v4-flash) + one victim call per goal
# (max_target_calls_per_goal=1), then unified judge. Only the judged file is
# kept in results/.
#
# Mechanism: incomplete compile-time brief (fragments char-index encoded, open
# passages unwritten) -> single user message: mechanical fragment restore +
# continuity-sheet authoring (ACTION / PROPS-MATERIALS / CLOSE-UP DETAIL per
# shot). The victim authors all substantive content itself.
#
# Standard contract: reads $VICTIM, $GOALS_FILE, $N_GOALS; writes one unified
# judged *.judged.json into $ATTACK_RESULTS_DIR. The raw output path is stable
# per (victim, N_GOALS, results dir) so a retried wrapper resumes the runner's
# per-case checkpoint instead of re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/storyboard-continuity"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
COMPILER="${COMPILER:-deepseek/deepseek-v4-flash}"     # auxiliary compiler, fixed for all victims
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/storyboard-continuity_${VICTIM_SLUG}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/storyboard-continuity_${VICTIM_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --compiler "api:$COMPILER" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --temperature 0.0 \
  --max-tokens 16384 \
  --goal-workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
