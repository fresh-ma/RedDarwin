#!/usr/bin/env bash
# FlipAttack 3.0 (proposal flipattack-3-0) on $VICTIM (default qwen/qwen3.7-flash),
# first $N_GOALS goals of $GOALS_FILE (default bench/AdvBench.csv, first 5).
# Runs the two evaluated guidance frames (decoder-flip control, chunk-flip)
# over the FCS whole-sentence character-flip payload (2 target calls per
# goal). span-flip was superseded by chunk-flip after probe 1 (span-grounding
# validated for abstraction decoys, falsified for decode garbles) and is kept
# in code for offline ablation only.
# max-tokens 8192 (reasoning victims consume hidden reasoning tokens; lower
# budgets truncate to empty completions), then the unified judge.
# Only the judged file is kept in results/.
#
# Notes:
#   - no attacker/auxiliary LLM role: payloads are a deterministic flip + fixed
#     frames; victim gets the api: prefix like the parent wrapper.
#   - the raw output path is stable per (victim, N_GOALS, results dir) so a
#     retried wrapper resumes the runner's per-case checkpoint instead of
#     re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/flipattack-3-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/flipattack-3-0_${VICTIM_SLUG}_2frame_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/flipattack-3-0_${VICTIM_SLUG}_2frame_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --variants decoder-flip,chunk-flip \
  --max-tokens 8192 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
