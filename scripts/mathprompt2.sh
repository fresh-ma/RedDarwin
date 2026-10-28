#!/usr/bin/env bash
# MathPrompt 2.0 (proposal mathprompt2) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv, first 5). One constructive-witness encoding per goal
# (attacker LLM + decode-check audit loop, cached on disk keyed by
# sha256(schema-hash+variant+goal)), then exactly ONE victim call per goal (parent budget:
# 1), then the unified judge. Only the judged file is kept in results/.
#
# Notes:
#   - auxiliary LLM (encoder + auditor) fixed to deepseek/deepseek-v4-flash per
#     project convention; victim params: temperature 0.0, max-tokens 8192
#     (deepseek victims burn several k tokens of meta-planning before the
#     final answer; 4096 truncated the payload mid-stream in probe 1).
#   - encodings are cached proposal-locally (identical payload per goal across
#     all 4 victims; memoized across probes and resumes).
#   - the raw output path is stable per (victim, N_GOALS, results dir) so a
#     retried wrapper resumes the runner's per-case checkpoints (and the
#     memoized encoding cache) instead of re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/mathprompt2"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VARIANTS="${VARIANTS:-constructive-witness}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

VARIANT_SLUG="${VARIANTS//,/+}"
RAW_OUT="$RESULTS/mathprompt2_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_raw.json"
JUDGED_TMP="$RESULTS/mathprompt2_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x.judged.json.tmp"
JUDGED_OUT="$RESULTS/mathprompt2_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --variants "$VARIANTS" \
  --attacker api:deepseek/deepseek-v4-flash \
  --encode-attempts 3 \
  --temperature 0.0 \
  --max-tokens 8192 --encode-max-tokens 2048 \
  --goal-workers "$GOAL_WORKERS" --retries 3 \
  --out "$RAW_OUT"

# 2) unified judge (token headroom: long victim outputs exhaust the 300-token
#    default via hidden reasoning; 1024 -> doubles to 2048/4096 on retry)
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_TMP" --max-tokens 1024
mv "$JUDGED_TMP" "$JUDGED_OUT"
