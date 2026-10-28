#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"
SLUG="${VICTIM##*/}"
STAMP="$(date +%Y%m%d-%H%M%S)"
RAW="$(mktemp -t talechameleon_raw_XXXXXX.json)"
trap 'rm -f "$RAW"' EXIT

"$PY" "$ROOT/XSkillLib/New-Proposal/talechameleon/scripts/attack.py" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" --target "api:$VICTIM" --out "$RAW"
"$PY" "$ROOT/judge/unified_judge.py" --input "$RAW" \
  --output "$RESULTS/talechameleon_${SLUG}_binary-tree_${N_GOALS}x_${STAMP}.judged.json"
