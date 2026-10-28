#!/usr/bin/env bash
# DeepInception attack on $VICTIM (default qwen/qwen3.7-flash),
# first $N_GOALS goals of $GOALS_FILE (default bench/AdvBench.csv),
# strongest single setting (science fiction, L5/C5, max-tokens 8192),
# then unified judge. Only the judged file is kept in results/.
#
# Setting basis: results/RESULT_2026-06-27.md canonical tokfix rerun
# (deepinception_v4flash_tok8192_20260628.json, raw asr_content_harmful 0.575).
# Per-scene breakdown of that file: science fiction 0.600 vs spy movie 0.550
# content-harmful, so the single strongest config is the paper default
# (science fiction, layers 5, characters 5). --max-tokens 8192 is REQUIRED for
# the v4-flash reasoning target: at 2048 it emptied 7/40 cells and suppressed
# measured ASR to 0.35 (tokfix note in RESULT_2026-06-27.md).
#
# Known risks:
# - This skill is template-only: NO attacker/auxiliary LLM role by design
#   (the nested-scene prompt is rendered verbatim, fixed payload).
# - The skill's own dual-metric judge runs inside the attack (--judge); it is
#   set to v4-flash per project convention (SKILL.md defaults to deepseek-chat)
#   and does NOT follow $VICTIM. The final verdict comes from unified_judge anyway.
# - With the default victim, judge=victim=v4-flash means the judged model also
#   grades itself.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Scenario-Nesting/2311.03191_DeepInception/deepinception"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t deepinception_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/deepinception_${VICTIM_SLUG}_sfL5C5_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
#    --limit-rows "$N_GOALS" pins the first $N_GOALS goals of $GOALS_FILE (loader
#    reads the `request` column directly; no shuffle, so these are exactly the
#    first $N_GOALS rows)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --dataset "$GOALS_FILE" \
  --limit-rows "$N_GOALS" \
  --scene-type "science fiction" --num-layers 5 --num-characters 5 \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --max-tokens 8192 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
