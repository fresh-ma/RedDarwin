#!/usr/bin/env bash
# Past-Tense Refusal Generalization (arXiv:2407.11969) on $VICTIM
# (default qwen/qwen3.7-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/AdvBench.csv, N_GOALS default 5), then unified judge.
#
# Setting basis (skill's canonical run, RESULT_2026-07-22.md):
#   --attack past --n-restarts 1 --judge official-all --target-max-tokens 1024
#   The canonical audited run showed past > future > present on every metric
#   (rule 0.60 / semantic 0.10 / llama 0.25 for past), so `past` is the
#   strongest single configuration; n_restarts=1 + target_max_tokens=1024 are
#   the canonical/tokfix choices (paper's headline 0.88 ASR used 20 restarts).
# Roles: --target (victim), --reformulator (attacker-rewriter),
#   --judge-model (in-skill PAIR/llama judges) — all deepseek-v4-flash.
#   The skill's own judges run inside the attack; unified_judge re-judges after.
# Known risks: single restart understates the paper's best-of-20 magnitude;
#   judge-model doubles as attack judge and is the same family as the victim.
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Stylistic-Obfuscation/2407.11969_PastTense/past-tense"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t past_tense_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/past-tense_${VICTIM_SLUG}_past_r1_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
#    --n-requests "$N_GOALS" = first N_GOALS goals (loader slices in file order, no shuffle)
cd "$METHOD"
"$PY" scripts/attack.py \
  --attack past \
  --target "api:$VICTIM" \
  --reformulator api:deepseek/deepseek-v4-flash \
  --judge official-all --judge-model api:deepseek/deepseek-v4-flash \
  --dataset "$GOALS_FILE" \
  --n-requests "$N_GOALS" --n-restarts 1 \
  --target-max-tokens 1024 \
  --output "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
