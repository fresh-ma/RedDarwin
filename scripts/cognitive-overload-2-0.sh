#!/usr/bin/env bash
# Cognitive Overload 2.0 (proposal cognitive-overload-2-0) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv, first 5). One auxiliary-LLM veil per goal (shared across
# variants, memoized in the checkpoint), then one target call per variant over
# $VARIANTS (default: dual-load; plain-briefing is the ablation control), then
# the unified judge. Only the judged file is kept in results/.
#
# Notes:
#   - target params: temperature 0.7, max-tokens 32768 — the dual-load
#     variant's mechanical decode needs the headroom, and reasoning victims
#     burn hidden tokens (puzzler-clue-2-0 probes: deepseek empty completions
#     on the decode task persisted at 16384).
#   - the raw output path is stable per (victim, N_GOALS, variants, results
#     dir) so a retried wrapper resumes the runner's per-case checkpoint
#     (including memoized veils) instead of re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/cognitive-overload-2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VARIANTS="${VARIANTS:-dual-load}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
VARIANT_SLUG="${VARIANTS//,/+}"
RAW_OUT="$RESULTS/cognitive-overload-2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/cognitive-overload-2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --variants "$VARIANTS" \
  --temperature 0.7 \
  --max-tokens 32768 --timeout 120 \
  --workers 5 --goal-workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
