#!/usr/bin/env bash
# CodeChameleon 5.0 (proposal codechameleon-5-0) on $VICTIM (default qwen/qwen3.7-flash),
# first $N_GOALS goals of $GOALS_FILE (default bench/AdvBench.csv, first 5).
# Runs both inherited carrier shells (commitment-shell control, trace-shell audit)
# re-lexiconed from concealment to transform-transparency vocabulary over the
# parent's v3.2 token-blind flip payload (2 target calls per goal), max-tokens
# 8192 (reasoning victims consume hidden reasoning tokens), then the unified
# judge. Only the judged file is kept in results/.
#
# Notes:
#   - no attacker/auxiliary LLM role: payloads are deterministic cipher + fixed
#     shells; victim gets the api: prefix like the parent wrapper.
#   - the raw output path is stable per (victim, N_GOALS, results dir) so a
#     retried wrapper resumes the runner's per-case checkpoint instead of
#     re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/codechameleon-5-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/codechameleon-5-0_${VICTIM_SLUG}_2shell_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/codechameleon-5-0_${VICTIM_SLUG}_2shell_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --variants commitment-shell,trace-shell \
  --max-tokens 8192 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
