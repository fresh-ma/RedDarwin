#!/usr/bin/env bash
# Persona-Modulation attack (arXiv 2311.03348) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv), strongest single setting, then unified judge.
#
# Setting basis: results/RESULT_2026-06-27.md canonical run (GLM-audited
# asr_content_harmful = 0.20, the strongest documented result) used
# max_tokens=1536; 3 of its 4 audited hits were at target temperature 0.0
# (vs 1 at 0.7), so we run t=0.0 only: --max-tokens 1536 --target-temperatures 0.0.
#
# Dataset: the skill's own loop iterates the paper's 43-category table and has
# no AdvBench input, so pipeline.py was minimally patched with --goals-csv:
# goals are read from the CSV `request` column and used VERBATIM as the misuse
# instruction (no MISUSE_TEMPLATE wrapping), keeping the judge goal-faithful.
#
# Known risks:
# - SKILL.md prescribes attacker = gryphe/mythomax-l2-13b because deepseek
#   frequently REFUSES to author jailbreak personas; per project convention the
#   attacker is still deepseek/deepseek-v4-flash here (attacker/judge do NOT
#   follow $VICTIM). pipeline.py has a fallback persona shell so a refused/empty
#   attacker reply does not drop the case, but ASR may be lower than the
#   canonical mythomax-attacker run.
# - pipeline.py talks to OpenRouter directly with bare model ids: --target
#   accepts and strips the api: prefix, but --attacker-model/--judge-model are
#   used raw, so they are passed WITHOUT the api: prefix.
# - pipeline.py success status was changed "completed" -> "ok" because
#   unified_judge.py only scores status ok/missing (provider errors keep
#   "provider_error:*" and are skipped).
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Persona-Roleplay/2311.03348_PersonaModulation/persona-modulation"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t persona_modulation_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/persona-modulation_${VICTIM_SLUG}_mt1536t0_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/pipeline.py \
  --goals-csv "$GOALS_FILE" \
  --sample-rows "$N_GOALS" \
  --target "api:$VICTIM" \
  --attacker-model deepseek/deepseek-v4-flash \
  --judge-model deepseek/deepseek-v4-flash \
  --target-temperatures 0.0 \
  --max-tokens 1536 \
  --request-delay 0.3 \
  --run-out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
