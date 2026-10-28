#!/usr/bin/env bash
# DeepInception 2.0 (proposal deepinception-2-0) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv), then unified judge. Only the judged file is kept in
# results/.
#
# Mechanism (evolution of deepinception, 2311.03191): the parent's nested
# layer-i-creates-layer-i+1 scene is kept, but the verbatim harmful goal in
# the layer-0 instruction is replaced by a fragment-distributed payload — an
# auxiliary attacker LLM (deepseek/deepseek-v4-flash, fallback deepseek/deepseek-v4-flash)
# decomposes the goal into one concrete operational component per layer, each
# layer discusses only its own component, and the final layer is an explicit
# cross-layer merge contract demanding specific, practical, real-world steps.
#
# Budget: 1 victim call per goal (same as parent) + 1 auxiliary attacker call
# per goal (memoized in the raw output, so retries and resumes never re-pay
# it). max-tokens 8192 is kept from the parent wrapper (required for the
# v4-flash reasoning victim; lower caps empty out cells and deflate ASR).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/deepinception-2-0"

VICTIM="${VICTIM:-qwen/qwen3.7-flash}"                # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
# Raw path is stable per (victim, N_GOALS, results dir): a retried wrapper
# resumes the runner's checkpoint (per-goal results + memoized decompositions).
RAW_OUT="$RESULTS/deepinception-2-0_${VICTIM_SLUG}_fragL5C5_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/deepinception-2-0_${VICTIM_SLUG}_fragL5C5_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" \
  --dataset "$GOALS_FILE" \
  --limit-rows "$N_GOALS" \
  --scene-type "science fiction" --num-layers 5 --num-characters 5 \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --max-tokens 32768 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
