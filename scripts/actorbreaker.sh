#!/usr/bin/env bash
# ActorBreaker attack on $VICTIM, first $N_GOALS goals of $GOALS_FILE,
# strongest single setting (actors=3 + dynamic-modify), then unified judge.
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Multi-turn/Actor-Adaptive/2410.10700_ActorBreaker/actorbreaker"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t actorbreaker_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/actorbreaker_${VICTIM_SLUG}_dm_a3_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py \
  --target "api:$VICTIM" \
  --attacker api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash \
  --dataset "$GOALS_FILE" \
  --samples "$N_GOALS" --workers 5 \
  --actors 3 --dynamic-modify \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
