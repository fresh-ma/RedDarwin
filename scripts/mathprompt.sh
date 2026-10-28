#!/usr/bin/env bash
# MathPrompt (arXiv:2409.11445 symbolic-math jailbreak) on $VICTIM (default
# deepseek/deepseek-v4-flash), $GOALS_FILE first $N_GOALS goals (defaults:
# AdvBench.csv, 5), strongest single setting = mathprompt (the attack
# itself; "direct" is only the paper's ~1% no-attack baseline, so we run the
# mathprompt setting alone, max_tokens 1024 per RESULT_2026-07-15.md), then
# unified judge. Only the judged file is kept in results/.
#
# Known risks / notes:
# - The skill's loader did not know the bench CSV's `request` column; a one-line
#   patch added "request" to _GOAL_COLS in the skill's scripts/cases.py
#   (loader reads rows in file order, so --sample N = the first N goals).
# - Paper's attacker (math encoder) is GPT-4o; we use deepseek-v4-flash per
#   project convention (the SKILL.md default substitute). A weaker encoder can
#   lower content_harmful; refusal_bypass was 1.00 in the skill's real runs.
# - SKILL.md bans GPT/Claude/Gemini targets (403/ban risk); deepseek-v4-flash
#   on OpenRouter is an allowed lab model.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Code-Encapsulation/2409.11445_MathPrompt/mathprompt"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t mathprompt_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/mathprompt_${VICTIM_SLUG}_mp_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
#    --sample $N_GOALS pins the first $N_GOALS goals (loader reads in file order)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --target "api:$VICTIM" \
  --attacker api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash \
  --dataset "$GOALS_FILE" \
  --sample "$N_GOALS" --workers 5 \
  --settings mathprompt --max-tokens 1024 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
