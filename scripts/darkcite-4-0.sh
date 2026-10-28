#!/usr/bin/env bash
# DarkCite 4.0 (proposal darkcite-4-0) on $VICTIM (default qwen/qwen3.7-flash),
# first $N_GOALS goals of $GOALS_FILE (default bench/AdvBench.csv, first 5).
# Runs the two evaluated frames (subject-cite control, split-cite) over the
# grandparent's released fabricated-citation trust carrier (2 target calls per
# goal), then the unified judge. Only the judged file is kept in results/.
#
# Notes:
#   - no runtime attacker/auxiliary LLM: citations are the released artifacts
#     plus 2 proposal-local offline-fabricated citations (data/); the blind
#     citations are inherited from the parent's offline data and the split
#     facets are written once offline by the fixed model
#     deepseek/deepseek-v4-flash (scripts/make_split_facets.py).
#   - gen params follow the grandparent's published setting (temp 0.9 /
#     top_p 0.9); max-tokens 8192 (reasoning victims consume hidden reasoning
#     tokens; lower budgets truncate to empty completions).
#   - the raw output path is stable per (victim, N_GOALS, results dir) so a
#     retried wrapper resumes the runner's per-case checkpoint instead of
#     re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/darkcite-4-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/darkcite-4-0_${VICTIM_SLUG}_2frame_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/darkcite-4-0_${VICTIM_SLUG}_2frame_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --variants subject-cite,split-cite \
  --temperature 0.9 --top-p 0.9 --max-tokens 8192 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
