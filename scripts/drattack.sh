#!/usr/bin/env bash
# DrAttack (2402.16914, prompt-decomposition jailbreak) on $VICTIM (default
# deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default AdvBench.csv),
# strongest single setting, then unified judge.
# Only the judged file is kept in results/.
#
# Setting rationale: canonical run results/drattack_v4flash_8x2_tokfix_20260626.json
# (results/RESULT_2026-06-27.md) evaluated two reconstruction settings,
# "noun" and "noun+verb"; the only refusal-bypass case came from "noun+verb"
# (more synonym substitution = stronger per the paper), so we run that single
# setting with the canonical tokfix knobs (topk-sub 3, sub-threshold 0.1,
# judge-max-tokens 4096 — v4-flash is a reasoning judge and smaller budgets
# truncate the Yes/No verdict).
#
# Roles: victim target = --target api:$VICTIM, harmfulness judge = --judge-model
# api:deepseek/deepseek-v4-flash (per task spec, which also matches the skill's
# documented default). There is NO attacker/assistant-LLM role by design: the
# decomposition is a cached GPT-4 phrase tree (data/prompts_information.json)
# and reconstruction is ICL served by the target itself; embedding fitness is
# local sentence-transformers all-MiniLM-L6-v2 on CPU (documented ada-002
# substitution), so no third model is needed.
#
# Known risks:
#  - Faithful negative expected: the canonical audited ASR vs v4-flash is 0.0
#    (decomposition does not transfer to this target); a 0 ASR here is the
#    finding, not a defect.
#  - First run may download the MiniLM embedding model (HF mirror exported
#    below as in break-me.sh); CPU-only, no GPU needed.
#  - No seeded-shuffle issue: read_goals preserves CSV order and --limit is
#    applied before any sampling, and AdvBench.csv's `request` column is in
#    the loader's auto-detect list, so --limit "$N_GOALS" = exactly the first
#    N_GOALS goals of $GOALS_FILE.
set -euo pipefail

# huggingface.co may be unreachable from this network; use the mirror so the
# embedding-fitness encoder (st:all-MiniLM-L6-v2) can download on first run.
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
# models are already in the local HF cache; skip hub HEAD checks (they hang
# for minutes on retries when the network is flaky) and load from cache.
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Single-turn/Multi-Strategy-Pool/2402.16914_DrAttack/drattack"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t drattack_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/drattack_${VICTIM_SLUG}_nounverb_tokfix_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --target "api:$VICTIM" \
  --judge-model api:deepseek/deepseek-v4-flash --judge-max-tokens 4096 \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --settings "noun+verb" --topk-sub 3 --sub-threshold 0.1 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
