#!/usr/bin/env bash
# Echo Chamber 2.0 (single-skill-evolution of echo-chamber) on $VICTIM,
# first $N_GOALS goals of $GOALS_FILE, then unified judge.
#
# Mechanism delta vs parent (see proposal SKILL.md / EXPERIMENTS.md):
#   - deniable-seed compiler: concept extraction + deniable glosses replace the
#     parent's broken keyword stage; attacker-side seed fallback on victim
#     seed refusal (no extra victim calls);
#   - frame-pivot steering: machine-computed <SteeringStatus> (last_outcome,
#     refusal_streak) drives strategy-level recovery instead of wording-only
#     re-asks.
# Budget parity with parent: max-turns 4 (outer 3 / inner 2) -> <=8 victim
# calls per goal; target-max-tokens 2048, attacker temp 0.5 / target temp 0.0.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/echo-chamber2-0"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
# Absolutize: the attack runs with cwd inside the proposal scripts dir.
GOALS_FILE="$(cd "$(dirname "$GOALS_FILE")" && pwd)/$(basename "$GOALS_FILE")"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t echo_chamber2_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/echo-chamber2-0_${VICTIM_SLUG}_mt4_tk2048_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the walk-up loader)
cd "$METHOD/scripts"
"$PY" attack.py run \
  --dataset "$GOALS_FILE" \
  --target "api:$VICTIM" \
  --attacker-model api:deepseek/deepseek-v4-flash \
  --judge-model api:deepseek/deepseek-v4-flash \
  --limit "$N_GOALS" --sample "$N_GOALS" \
  --max-turns 4 --target-max-tokens 2048 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT" --max-tokens 2000
