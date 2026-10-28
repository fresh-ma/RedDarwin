#!/usr/bin/env bash
# ArtPrompt (2402.11753, ASCII-art masked-word cloaking) on $VICTIM (default
# deepseek-v4-flash), first $N_GOALS goals from $GOALS_FILE (default AdvBench.csv
# first 5), then unified judge.
#
# Setting (canonical tokfix, results/RESULT_2026-06-26.md + GLM_REVIEW_tokfix_20260626.md):
#   fonts=gen,cards --direction h --masker dataset, target --max-tokens 8000,
#   --judge-max-tokens 2048. Rationale: v4-flash is a reasoning model whose
#   ASCII-parse reasoning exhausted the default 512-token budget (8 empty outputs
#   in the first-pass run); the tokfix budget is the audited canonical config
#   (audited asr_gpt_judge = 0.0625, the only GLM-confirmed harmful case).
#
# Known risks / notes:
#   - No attacker LLM in this design: the transform is deterministic. The only
#     auxiliary-LLM role is --masker llm; canonical uses --masker dataset
#     (per-row category column), so no attacker calls are made.
#     (--masker-model is still defaulted to api:deepseek/deepseek-v4-flash.)
#   - SKILL.md warns OpenRouter 403-blocks the official GPT-Judge prompt for some
#     providers; historical v4-flash runs scored fine via OpenRouter, and final
#     scoring is done by unified_judge anyway. If the in-attack gpt_judge fails,
#     dict_judge + unified_judge output are still produced.
#   - --judge stays on the default OpenRouter base URL (same as historical runs).
#
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Single-turn/Encoding-Linguistic/2402.11753_ArtPrompt/artprompt"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t artprompt_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/artprompt_${VICTIM_SLUG}_tokfix_gen_cards_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
# --limit $N_GOALS + --sample-rows $N_GOALS: loader takes rows[:N] first, and since
# sample_rows == len(selected) the seeded shuffle is skipped -> exactly the
# first $N_GOALS `request` rows of $GOALS_FILE (normalize_rows auto-detects the column).
cd "$METHOD"
"$PY" scripts/attack.py run \
  --goals "$GOALS_FILE" \
  --limit "$N_GOALS" --sample-rows "$N_GOALS" \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --fonts gen,cards --direction h --masker dataset \
  --max-tokens 8000 --judge-max-tokens 2048 --request-delay 0.4 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
