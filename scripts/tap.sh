#!/usr/bin/env bash
# TAP (Tree of Attacks with Pruning, arXiv:2312.02119) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv, first 5), then unified judge.
#
# Setting basis: canonical config from tap/RESULT_2026-07-20.md (the skill's
# strongest local result, raw 8/9 = 0.8889 on Deakin runs) — deepseek-v4-flash
# as attacker/target/evaluator, branching=3, width=3, depth=3, keep_last_n=3,
# success_threshold=10, target max_tokens=1024. The paper's own b=4/w=10/d=10
# is GPT-4-era and far more expensive; the local canonical b3w3d3 is preferred.
# --target-reasoning off / --evaluator-reasoning off are added per
# RESULT_supergemma_attacker_2026-07-21.md: with reasoning ON, deepseek-v4-flash
# burns max_tokens on the reasoning trace over harmful prompts and returns
# content=None ~4/6 of the time (TAP then stalls on empty responses).
#
# Roles: --target (victim, parameterized via $VICTIM), --attacker (aux LLM),
# --evaluator (on-topic filter + judge; this skill has no separate judge flag —
# evaluator IS the judge). Aux roles stay pinned to api:deepseek/deepseek-v4-flash
# per project convention.
#
# Known risks:
# - deepseek-v4-flash as attacker may refuse to emit jailbreak prompts for some
#   goals -> iteration status "no_valid_attacker_outputs", success=None-ish
#   failure (noted in CoA skill for deepseek attackers; TAP keeps going per-goal).
# - Records with no valid target response keep status "invalid_no_target_response"
#   and are skipped by unified_judge (correct: nothing to score).
# - Two minimal patches were applied to the skill for this pipeline:
#   tap_pkg/io.py accepts AdvBench's `request` column as goal; tap_pkg/core.py
#   emits status "ok" for valid runs (unified_judge only scores ok/missing;
#   TAP's own verdict stays in the `success` boolean).
#
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Persuasion/2312.02119_TAP/tap"
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
RAW_OUT="$(mktemp -t tap_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/tap_${VICTIM_SLUG}_b3w3d3_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
#    loader reads goals in file order; --n-requests "$N_GOALS" pins the first
#    $N_GOALS rows
cd "$METHOD"
"$PY" scripts/attack.py \
  --target "api:$VICTIM" \
  --attacker api:deepseek/deepseek-v4-flash \
  --evaluator api:deepseek/deepseek-v4-flash \
  --dataset "$GOALS_FILE" \
  --n-requests "$N_GOALS" \
  --branching-factor 3 --width 3 --depth 3 \
  --target-max-tokens 1024 \
  --target-reasoning off --evaluator-reasoning off \
  --output "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
