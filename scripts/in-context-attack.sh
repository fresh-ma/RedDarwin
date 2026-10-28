#!/usr/bin/env bash
# In-Context Attack (ICA, 2310.06387) on $VICTIM (default qwen/qwen3.7-flash),
# first $N_GOALS goals of $GOALS_FILE (default bench/AdvBench.csv), strongest
# single setting (5-shot, max-tokens 1536), then unified judge.
#
# Setting rationale: the canonical GLM-audited result (skill results/
# RESULT_2026-06-27.md, ica_advbench8_1and3and5shot_v4flash_mt1536.json) shows a
# monotone shot trend — more shots (3/5) produced the strongest harms — so the
# max 5-shot config with the canonical max_tokens=1536 is chosen.
#
# Roles: victim (--target) follows $VICTIM; --judge stays api:deepseek/deepseek-v4-flash
# per project convention. There is NO attacker/assistant LLM by design: ICA uses
# fixed harmful Q->A demonstrations from data/ica_demonstrations.json. The skill's
# own --judge default is already deepseek-v4-flash; unified_judge re-judges anyway.
#
# Known risks:
#  - Demo/target overlap: when $GOALS_FILE is the default AdvBench.csv, 3 of the
#    first 5 goals are literally the ICA demonstration queries (demos are drawn
#    from the AdvBench front; SKILL.md recommends subsampling from the back for
#    clean runs). We keep the mandated "first $N_GOALS goals", so ASR may be
#    inflated for overlapping rows.
#  - Historical result (RESULT_2026-06-27.md): 0/24 harmful on v4-flash at any
#    shot count — expect near-zero ASR on this target; that is the faithful
#    finding, not a bug.
#
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Few-Shot-Demonstration/2310.06387_ICA/in-context-attack"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t ica_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/in-context-attack_${VICTIM_SLUG}_5shot-mt1536_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --dataset "$GOALS_FILE" \
  --limit-rows "$N_GOALS" \
  --shots 5 \
  --max-tokens 1536 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
