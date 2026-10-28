#!/usr/bin/env bash
# CipherChat 2.0 (proposal cipherchat2-0) on $VICTIM (default qwen/qwen3.7-flash),
# first $N_GOALS goals of $GOALS_FILE (default bench/AdvBench.csv, first 5).
# Genuine word-reversal cipher: cipher rule + fully enciphered unsafe demos in the
# system prompt, enciphered goal, victim answers in cipher, local deterministic
# decode, then the unified judge. One victim call per goal (same as parent).
# Only the judged file is kept in results/.
# Resume: the raw output path is stable per (victim, N_GOALS, results dir), so a
# retried wrapper resumes the runner's per-case checkpoint instead of re-paying
# completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/cipherchat2-0"
VICTIM="${VICTIM:-qwen/qwen3.7-flash}"                # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/cipherchat2-0_${VICTIM_SLUG}_wordrev_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/cipherchat2-0_${VICTIM_SLUG}_wordrev_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --temperature 0 --max-tokens 8192 \
  --workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
