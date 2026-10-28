#!/usr/bin/env bash
# LASH 2.0 (deflection-gated adaptive semantic hybridization; evolution of
# lash, proposal lash-2-0) on $VICTIM, first $N_GOALS goals of $GOALS_FILE,
# then unified judge. Only the judged file is kept in results/.
#
# Same role/budget settings as the parent wrapper scripts/lash.sh for a
# controlled comparison: all four roles forced to deepseek/deepseek-v4-flash,
# paper GA defaults (P=8, G=2, sigma=0.6, tau=9, seed budgets 5/5/10), GA
# target-query budget 50 (--max-target-queries 50), judge/attacker caps raised
# for the reasoning judge/attacker (4096/2048) and the composition cap raised
# to 4096 after probe 1 showed reasoning-model finish_reason=length
# truncations at the inherited 2048 cap (same documented parent risk class).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/lash-2-0"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

RAW_OUT="$RESULTS/lash-2-0_${VICTIM_SLUG}.raw.json"
JUDGED_OUT="$RESULTS/lash-2-0_${VICTIM_SLUG}.judged.json"
JUDGED_TMP="$RESULTS/.lash-2-0_${VICTIM_SLUG}.judged.tmp.json"

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up
#    loader; --sample "$N_GOALS" takes the first N_GOALS rows; checkpoints
#    after every case and resumes on re-run with the same --out)
"$PY" "$METHOD/scripts/attack.py" \
  --target-model "$VICTIM" \
  --judge-model deepseek/deepseek-v4-flash \
  --attacker-model deepseek/deepseek-v4-flash \
  --composition-model deepseek/deepseek-v4-flash \
  --judge-max-tokens 4096 --attacker-max-tokens 2048 --composition-max-tokens 4096 \
  --dataset "$GOALS_FILE" \
  --sample "$N_GOALS" --max-target-queries 50 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
"$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_TMP"
mv "$JUDGED_TMP" "$JUDGED_OUT"
