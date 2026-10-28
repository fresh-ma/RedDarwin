#!/usr/bin/env bash
# PAP 2.0 wrapper — reads VICTIM, GOALS_FILE, N_GOALS; writes one unified judged
# *.judged.json into ATTACK_RESULTS_DIR.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/pap-2-0"
VICTIM="${VICTIM:-qwen/qwen3.7-flash}"
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
# ensure absolute path before cd'ing into method dir
if [[ ! "$GOALS_FILE" = /* ]]; then
  GOALS_FILE="$ROOT/$GOALS_FILE"
fi
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/pap-2-0-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/pap-2-0_${VICTIM_SLUG}_${N_GOALS}x_${STAMP}.json"
JUDGED_OUT="$RESULTS/pap-2-0_${VICTIM_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

# Run the adaptive persuasion attack (PAP 2.0)
cd "$METHOD"
"$PY" scripts/attack.py \
  --attacker-model deepseek/deepseek-v4-flash \
  --target-model "$VICTIM" \
  --judge-model deepseek/deepseek-v4-flash \
  --dataset "$GOALS_FILE" \
  --sample "$N_GOALS" \
  --max-tokens 1536 \
  --request-delay 0.5 \
  --max-attempts 2 \
  --out "$RAW_OUT"

# Apply the unified judge for cross-attack comparability
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT" --model api:deepseek/deepseek-v4-flash

# Copy/move the judged file to ATTACK_RESULTS_DIR root so the harness finds it
# even if attack.py placed it inside results/
if [[ "$RESULTS" != "$ATTACK_RESULTS_DIR" ]] && [[ -n "${ATTACK_RESULTS_DIR:-}" ]]; then
  cp "$JUDGED_OUT" "$ATTACK_RESULTS_DIR/"
fi
