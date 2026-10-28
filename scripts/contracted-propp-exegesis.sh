#!/usr/bin/env bash
# ContractedProppExegesis (proposal contracted-propp-exegesis) on $VICTIM
# (default qwen/qwen3.7-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/AdvBench.csv, first 5). One compiled contracted-exegesis
# prompt per goal = 1 target call per goal; the shared validated-plan cache
# under the proposal's plan_cache/ is reused across victims and resumes.
# Runs the unified judge afterwards; only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
METHOD="$ROOT/XSkillLib/Proposal/contracted-propp-exegesis"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
VICTIM_SLUG="${VICTIM##*/}"
RAW_OUT="$RESULTS/contracted-propp-exegesis_${VICTIM_SLUG}.raw.json"
JUDGED_OUT="$RESULTS/contracted-propp-exegesis_${VICTIM_SLUG}.judged.json"
JUDGED_TMP="$RESULTS/.contracted-propp-exegesis_${VICTIM_SLUG}.judged.tmp.json"

mkdir -p "$RESULTS"

"$PY" "$METHOD/scripts/attack.py" run \
  --goals "$GOALS_FILE" \
  --limit "$N_GOALS" \
  --target "$VICTIM" \
  --output "$RAW_OUT"

"$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_TMP"
mv "$JUDGED_TMP" "$JUDGED_OUT"
