#!/usr/bin/env bash
# ReNeLLM 2.0 (proposal renellm2-0) on $VICTIM (default qwen/qwen3.7-flash),
# first $N_GOALS goals of $GOALS_FILE (default bench/advbench_50.csv, first 5).
# FROZEN VARIANT: coded-narrative (best mean ASR across the panel in
# rounds 3-4: qwen 11/30, gpt-oss 15/28, deepseek 14/29, luna 1/30).
# One defense-inversion payload per goal (Stage A: auxiliary attacker lists
# DEFENSIVE measures; Stage B: deterministic inversion), then one target call
# per variant over $VARIANTS (default: canonical control + coded-analysis,
# the round-2 flip-surface frame; analysis-frame/manuscript-exegesis are
# probe-only alternatives and the final freezes one variant), then the
# unified judge.
# Only the judged file is kept in $ATTACK_RESULTS_DIR.
#
# Notes:
#   - max-tokens 131072: reasoning victims burn hidden tokens before the
#     visible completion, and the coded variants' position-by-position decode
#     plus full-length continuation needs the headroom (deepseek-v4-flash
#     returned empty completions at 32768 on long payloads; the provider
#     allows up to 384k completion tokens). Same budget for every victim —
#     no victim-keyed settings.
#   - the raw output path is stable per (victim, N_GOALS, variants, results
#     dir) so a retried wrapper resumes the runner's per-case checkpoint
#     (including memoized payloads) instead of re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/renellm2-0"
VICTIM="${VICTIM:-qwen/qwen3.7-flash}"                 # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VARIANTS="${VARIANTS:-coded-narrative}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
VARIANT_SLUG="${VARIANTS//,/+}"
RAW_OUT="$RESULTS/renellm2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/renellm2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --variants "$VARIANTS" \
  --temperature 0.7 --attack-temperature 1.0 \
  --max-tokens 131072 --max-measures 12 \
  --workers 5 --goal-workers "$GOAL_WORKERS" \
  --attack-retries 4 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
