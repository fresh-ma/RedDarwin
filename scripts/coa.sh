#!/usr/bin/env bash
# CoA (Chain of Attack) on $VICTIM, first $N_GOALS goals of $GOALS_FILE,
# deepest chain budget (5 rounds), then unified judge.
# Only the judged file is kept in results/.
# NOTE: attacker is v4-flash per project convention; the skill's SKILL.md warns
# deepseek may refuse to generate attack chains (chain_parse_failed cases).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Multi-turn/Actor-Adaptive/2405.05610_CoA/coa"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t coa_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/coa_${VICTIM_SLUG}_r5_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
#    --limit $N_GOALS pins the first $N_GOALS rows of $GOALS_FILE before the
#    skill's seeded shuffle
cd "$METHOD"
"$PY" scripts/attack.py run \
  --goals "$GOALS_FILE" \
  --target "api:$VICTIM" \
  --attacker api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash \
  --limit "$N_GOALS" --sample-rows "$N_GOALS" --max-rounds 5 --seed 20260626 \
  --target-max-tokens 2048 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
