#!/usr/bin/env bash
# ArtPrompt 2.0 (proposal artprompt-2-0) on $VICTIM (default deepseek-v4-flash),
# first $N_GOALS goals of $GOALS_FILE (default bench/advbench_50.csv), then the
# unified judge. One victim call per goal (parent used 2: gen+cards); the
# multi-word masker helper (api:deepseek/deepseek-v4-flash, fixed, victim-independent)
# is memoized per goal via the runner's checkpoint dir, so a retried wrapper
# resumes completed cases instead of re-paying them.
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/artprompt-2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

RAW_OUT="$RESULTS/artprompt-2-0_${VICTIM_SLUG}_fragmask_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/artprompt-2-0_${VICTIM_SLUG}_fragmask_${N_GOALS}x.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --masker-model api:deepseek/deepseek-v4-flash \
  --max-tokens 8000 --masker-max-tokens 2048 \
  --goal-workers "$GOAL_WORKERS" --retries 3 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
