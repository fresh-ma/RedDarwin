#!/usr/bin/env bash
# FITD 2.0 attack on $VICTIM, first $N_GOALS goals of $GOALS_FILE, then unified judge.
#
# Evolution of fitd (arXiv:2402.15690): background -> villain -> journal with a
# context-carried payload (no verbatim goal restatement at the final turn),
# payload-preserving decomposition on refusal, and a realism-revision pass on
# self-sanitized fiction. Deterministic attacker; <=8 victim calls per goal.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/fitd2-0"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash-0731}"
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
# absolutize (attack.py changes cwd into the proposal dir)
GOALS_FILE="$(cd "$(dirname "$GOALS_FILE")" && pwd)/$(basename "$GOALS_FILE")"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t fitd2_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/fitd2-0_${VICTIM_SLUG}_bvj_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --samples "$GOALS_FILE" --sample-rows "$N_GOALS" \
  --target "api:$VICTIM" \
  --judge-model deepseek/deepseek-v4-flash \
  --max-tokens 3072 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT" --max-tokens 1200
