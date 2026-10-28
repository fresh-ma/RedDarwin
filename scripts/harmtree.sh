#!/usr/bin/env bash
# HarmTree repair (TAP tree search over composed h4rm3l programs on incomplete
# source sketches) on $VICTIM, first $N_GOALS goals of $GOALS_FILE, then
# unified judge.
#
# Multi-skill combination of tap-2-0 (strategy-diverse b3w3d3 tree, judge v2)
# and h4rm3l2-0 (source-sketch -> CharIndexFlip -> reverse-causal development
# program). Same victim-call budget as both parents' shared cap: width 3 x
# depth 3 = <=9 target calls per goal. Aux roles (attacker, evaluator/judge)
# stay pinned to api:deepseek/deepseek-v4-flash per project convention.
#
# Frozen variant defaults: --strategy-diverse on --judge-version 2, compiled
# program families 1/6/7 with guaranteed root coverage (see EXPERIMENTS.md).
# Env overrides exist only for probe-time ablations.
STRATEGY_DIVERSE="${STRATEGY_DIVERSE:-on}"
JUDGE_VERSION="${JUDGE_VERSION:-2}"
STRATEGY_STALL_SCORE="${STRATEGY_STALL_SCORE:-3}"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/harmtree"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
# resolve to an absolute path before cd "$METHOD" below
case "$GOALS_FILE" in /*) ;; *) GOALS_FILE="$ROOT/$GOALS_FILE" ;; esac
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
# Attempt-stable checkpoint anchor: the evaluator gives each attempt a fresh
# ATTACK_RESULTS_DIR (.../<victim-slug>/attempt-<N>/shards/<goal>/results), so
# the intra-goal ckpt must NOT live under it. Strip any trailing
# /attempt-<N>/... components so all attempts of the same evaluation share one
# ckpt dir; direct wrapper runs (no attempt component) keep their own results
# dir as the base. attack.py still validates goal text + settings fingerprint
# before reusing any checkpoint.
CKPT_BASE="$RESULTS"
case "$CKPT_BASE" in
  */attempt-*) CKPT_BASE="${CKPT_BASE%%/attempt-*}" ;;
esac
CKPT_DIR="$CKPT_BASE/ckpt"
# Deterministic raw path (per victim/goals/shard-results dir) so an evaluator-killed
# wrapper rerun within one attempt also resumes instead of restarting. Removed
# on clean exit; the checkpoint directory survives across attempts. The results-dir
# hash keeps concurrent shards of the same victim from sharing one raw path (their
# EXIT traps would otherwise delete each other's file mid-judge).
SHARD_ID="$(printf '%s' "$RESULTS" | shasum | cut -c1-8)"
RAW_OUT="$CKPT_DIR/.harmtree_${VICTIM_SLUG}_sd${STRATEGY_DIVERSE}jv${JUDGE_VERSION}_${N_GOALS}x_${SHARD_ID}.raw.json"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/harmtree_${VICTIM_SLUG}_sd${STRATEGY_DIVERSE}jv${JUDGE_VERSION}_b3w3d3_${N_GOALS}x_${STAMP}.judged.json"

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
  --checkpoint-dir "$CKPT_DIR" \
  --output "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT" --max-tokens 1200
