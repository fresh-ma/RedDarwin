#!/usr/bin/env bash
# Stochastic Monkeys (arXiv 2411.02785) best-of-n random-augmentation jailbreak
# on $VICTIM (default deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE
# (default AdvBench.csv), then unified judge.
# Only the judged file is kept in results/.
#
# Setting: character_edit, k=25, p=0.05, gamma=0 — the paper-default knobs and
# the exact configuration of the skill's canonical run in results/
# (stochastic-monkeys_..._character_edit_k25_p0.05_10x_*.json).
#
# Known risks / notes:
# - No attacker LLM by design (pure random-augmentation payload transform);
#   only --target (victim, api:$VICTIM) and --judge (pinned to v4-flash) exist.
# - The skill's loader now accepts AdvBench's `request` column (patched
#   _PROMPT_KEYS in scripts/cases.py); --sample "$N_GOALS" takes the FIRST
#   N_GOALS rows (loader is in-order, no shuffle).
# - A resumable .jsonl still lands in the skill's own results/ dir per run;
#   only the raw .json is redirected to the mktemp file via the patched --out.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Single-turn/Multi-Strategy-Pool/2411.02785_StochasticMonkeys/stochastic-monkeys"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t stochastic-monkeys_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/stochastic-monkeys_${VICTIM_SLUG}_ce_k25_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --dataset "$GOALS_FILE" \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --augmentation character_edit -k 25 -p 0.05 --gamma 0 \
  --sample "$N_GOALS" --workers 5 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
