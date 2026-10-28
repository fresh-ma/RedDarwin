#!/usr/bin/env bash
# Humor Jailbreak Attack 2.0 (proposal humor-jailbreak-attack2-0) on $VICTIM
# (default deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/advbench_50.csv, first 5). One humor-compiler transform per
# goal (goal -> comedic bit premise, cached on disk keyed by sha256(goal)),
# then exactly ONE victim call per goal in the parent's humor shell with the
# output act shifted to bit continuation (variant: bit-continuation), then the
# unified judge. Only the judged file is kept in results/.
#
# Notes:
#   - victim params: temperature 0.0, max-tokens 4096 (1024 truncated reasoning-
#     spill deliberation mid-output in probe 1 — pure infra fix); the transform
#     helper gets max-tokens 4096 (helper chain-of-thought headroom before the
#     bit premise).
#   - the raw output path is stable per (victim, N_GOALS, variants, results
#     dir) so a retried wrapper resumes the runner's per-case checkpoints
#     (including the memoized bit cache) instead of re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/humor-jailbreak-attack2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VARIANTS="${VARIANTS:-bit-continuation}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

VARIANT_SLUG="${VARIANTS//,/+}"
RAW_OUT="$RESULTS/humor-jailbreak-attack2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_raw.json"
JUDGED_TMP="$RESULTS/humor-jailbreak-attack2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x.judged.json.tmp"
JUDGED_OUT="$RESULTS/humor-jailbreak-attack2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --dataset "$GOALS_FILE" --limit-rows "$N_GOALS" \
  --variants "$VARIANTS" \
  --transform-model api:deepseek/deepseek-v4-flash \
  --temperature 0.0 \
  --max-tokens 4096 --transform-max-tokens 4096 \
  --goal-workers "$GOAL_WORKERS" --retries 3 \
  --out "$RAW_OUT"

# 2) unified judge -> tmp then atomic mv to the final judged file
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_TMP"
mv "$JUDGED_TMP" "$JUDGED_OUT"
