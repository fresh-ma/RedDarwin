#!/usr/bin/env bash
# CodeAttack (arXiv 2403.07865) on $VICTIM (default qwen/qwen3.7-flash),
# $GOALS_FILE first $N_GOALS goals (defaults: AdvBench.csv, 5),
# then unified judge. Only the judged file is kept in results/.
#
# Setting: python_stack_plus (the skill's default prompt type). Basis: paper
# Table 1 average ASR — stack family 78% > queue/list 68% > string 51%, and the
# "_plus" variants are the paper's full three-part template; the historical local
# probe (results/zh_harmful_5_v4flash_20260714.json) also used python_stack_plus.
# Target/judge token budgets left at the canonical defaults (512/1000) that
# RESULT_2026-07-01.md aligned to the official repo.
#
# Roles: victim = --target (parameterized via $VICTIM), in-skill policy judge =
# --judge-model (pinned to deepseek-v4-flash, per harness policy). No attacker/
# helper LLM role exists —
# CodeAttack is a fixed template transformation (goal -> code-completion prompt).
#
# Known risks:
# - Loader reads the goals CSV's `request` column natively (io.py maps
#   request -> goal); --n-requests $N_GOALS with --start-idx 0 selects the first
#   $N_GOALS rows in file order (no shuffle), verified offline.
# - Unified judge scores the record-level `final_response` (raw target output),
#   not `final_extracted_response`; the in-skill policy judge still scores the
#   post-processed extraction, so the two ASR numbers may differ.
# - 512-token target budget can truncate long output_list completions; cases
#   with empty/invalid outputs are excluded from the in-skill ASR denominator
#   but still judged by the unified judge on whatever text exists.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Code-Encapsulation/2403.07865_CodeAttack/codeattack"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t codeattack_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/codeattack_${VICTIM_SLUG}_stackplus_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py \
  --dataset "$GOALS_FILE" \
  --n-requests "$N_GOALS" --start-idx 0 \
  --prompt-type python_stack_plus \
  --target "api:$VICTIM" \
  --judge policy --judge-model api:deepseek/deepseek-v4-flash \
  --output "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
