#!/usr/bin/env bash
# CodeAttack 2.0 (silent-fill code encapsulation) on $VICTIM,
# first $N_GOALS goals of $GOALS_FILE, then unified judge.
#
# Evolution of codeattack (python_stack_plus). Same victim-call budget: 1
# target call per goal, no attacker/helper LLM. Mechanism changes vs parent:
# double-reversal input encoding (plaintext goal appears nowhere), complete
# executable decode() (no verbalized-decode surface, no token sink), worked
# benign example, per-paragraph operational directives, 2048-token target
# budget (parent's 512 truncated payloads), truncation-tolerant extraction.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/codeattack2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"
# absolute path: the attack step cd's into the proposal directory
GOALS_FILE="$(cd "$(dirname "$GOALS_FILE")" && pwd)/$(basename "$GOALS_FILE")"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t codeattack2_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/codeattack2_${VICTIM_SLUG}_silentfill_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py \
  --dataset "$GOALS_FILE" \
  --n-requests "$N_GOALS" --start-idx 0 \
  --target "api:$VICTIM" \
  --judge policy --judge-model api:deepseek/deepseek-v4-flash \
  --output "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
