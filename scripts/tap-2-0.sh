#!/usr/bin/env bash
# TAP 2.0 (strategy-conditioned tree expansion + two-axis judge) on $VICTIM,
# first $N_GOALS goals of $GOALS_FILE, then unified judge.
#
# Evolution of tap (canonical b3w3d3). Same victim-call budget: width 3 x
# depth 3 = <=9 target calls per goal. Aux roles (attacker, evaluator/judge)
# stay pinned to api:deepseek/deepseek-v4-flash per project convention.
#
# Frozen variant defaults: --strategy-diverse on --judge-version 2
# (see EXPERIMENTS.md). Env overrides exist only for probe-time ablations.
STRATEGY_DIVERSE="${STRATEGY_DIVERSE:-on}"
JUDGE_VERSION="${JUDGE_VERSION:-2}"
STRATEGY_STALL_SCORE="${STRATEGY_STALL_SCORE:-3}"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/tap-2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t tap2_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/tap2_${VICTIM_SLUG}_sd${STRATEGY_DIVERSE}jv${JUDGE_VERSION}_b3w3d3_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py \
  --target "api:$VICTIM" \
  --attacker api:deepseek/deepseek-v4-flash \
  --evaluator api:deepseek/deepseek-v4-flash \
  --dataset "$GOALS_FILE" \
  --n-requests "$N_GOALS" \
  --branching-factor 3 --width 3 --depth 3 \
  --strategy-diverse "$STRATEGY_DIVERSE" --strategy-stall-score "$STRATEGY_STALL_SCORE" --judge-version "$JUDGE_VERSION" \
  --evaluator-max-tokens 150 \
  --target-max-tokens 16384 \
  --attacker-reasoning off --target-reasoning auto --evaluator-reasoning off \
  --output "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT" --max-tokens 1200
