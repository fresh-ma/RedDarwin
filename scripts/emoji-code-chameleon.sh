#!/usr/bin/env bash
# EmojiCodeChameleon (proposal emoji-code-chameleon) on $VICTIM, first
# $N_GOALS goals of $GOALS_FILE, then unified judge.
# Multi-skill combination of emoji-jailbreak2-0 (auxiliary-compiler emoji
# rebus) and codechameleon-2-0 (decrypt-then-complete ProblemSolver frame with
# task contract), fused through one shared representation: the rebus is the
# encrypted payload and the legend is code data inside the decryption
# function, extended with a tamper-evident audit_contract() stage.
# Budget: 1 victim call per goal + 1 auxiliary compiler call
# (deepseek/deepseek-v4-flash) per goal.
# Only the judged file is kept in results/.
#
# Standard contract: reads $VICTIM, $GOALS_FILE, $N_GOALS; writes one unified
# judged *.judged.json into $ATTACK_RESULTS_DIR.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/emoji-code-chameleon"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"      # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VARIANT="${VARIANT:-rebus-pipeline-shell}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"

VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
# Stable raw path per (victim, N_GOALS, results dir): a retried wrapper resumes
# the runner's per-case checkpoint instead of re-paying completed cases.
RAW_OUT="$RESULTS/emoji-code-chameleon_${VICTIM_SLUG}_${VARIANT}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/emoji-code-chameleon_${VICTIM_SLUG}_${VARIANT}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" \
  --limit "$N_GOALS" \
  --variant "$VARIANT" \
  --temperature 0.0 \
  --max-tokens 8192 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT" --max-tokens 1200
