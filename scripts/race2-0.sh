#!/usr/bin/env bash
# RACE 2.0 (goal-progress-gated ASM + operational output contract + synthesis
# turn) on $VICTIM, first $N_GOALS goals of $GOALS_FILE, then unified judge.
#
# Evolution of race (canonical t5 s3). Same victim-call budget: <=2 calls per
# turn x 5 turns = <=10 target calls per goal. Aux roles (shadow/judge) pinned
# to api:deepseek/deepseek-v4-flash with fallback api:deepseek/deepseek-v4-flash per AGENTS.md.
#
# Frozen variant defaults: --turns 5 --seeds 3, soft turns 1-3, pivot
# inversion off (see EXPERIMENTS.md probes 6a/6b).
# RACE2_SOFT_TURNS / RACE2_INVERT are probe-time ablation knobs forwarded to
# the attack script.
TURNS="${TURNS:-5}"
SEEDS="${SEEDS:-3}"
export RACE2_SOFT_TURNS="${RACE2_SOFT_TURNS:-3}"
export RACE2_INVERT="${RACE2_INVERT:-off}"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/race2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
[[ "$GOALS_FILE" = /* ]] || GOALS_FILE="$ROOT/${GOALS_FILE#./}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
TAG="advbench${N_GOALS}_$STAMP"
RAW_OUT="$RESULTS/race2_${VICTIM_SLUG}_t${TURNS}s${SEEDS}_${N_GOALS}x_${STAMP}.raw.json"
JUDGED_OUT="$RESULTS/race2_${VICTIM_SLUG}_t${TURNS}s${SEEDS}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/race2_attack.py \
  --victim "api:$VICTIM" \
  --shadow api:deepseek/deepseek-v4-flash \
  --judge  api:deepseek/deepseek-v4-flash \
  --data "$GOALS_FILE" \
  --sample "$N_GOALS" --turns "$TURNS" --seeds "$SEEDS" \
  --workers "$GOAL_WORKERS" \
  --victim-max-tokens 4096 --tag "$TAG" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT" --max-tokens 1200
