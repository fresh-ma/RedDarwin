#!/usr/bin/env bash
# ReNeLLM (2311.08268, rewrite + scenario nesting) attack on $VICTIM (default
# deepseek/deepseek-v4-flash), $GOALS_FILE first $N_GOALS goals (defaults:
# AdvBench.csv, 5), then unified judge.
# Only the judged file is kept in results/.
#
# Setting basis (results/RESULT_2026-06-25.md, canonical): strongest scenario =
# text_continuation (on-topic ASR 0.60 vs table_filling 0.40 / code_completion 0.20),
# T=10 iterations, goal-fidelity judge (default on), seed 20260608, default
# --target-max-tokens 256 (canonical text_continuation file had no ok-but-empty
# outputs; the mt8192 tokfix only applied to code_completion).
#
# Known risks:
# - Canonical config used gryphe/mythomax-l2-13b as the rewrite/attacker model
#   because deepseek-v4-flash silently refuses ~77% of rewrite ops (empty output,
#   counted as attack failure). Per task policy all roles are pinned to
#   deepseek-v4-flash, so expect the faithful-run ASR (~0.23 overall, text_continuation
#   ~0.30) rather than the canonical 0.60 — this measures v4-flash-as-attacker,
#   not the attack's full strength.
# - Cases where the rewrite never passes end with status=no_target_call and are
#   skipped by unified_judge (only status=ok is scored), consistent with the
#   historical judged runs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Scenario-Nesting/2311.08268_ReNeLLM/renellm"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t renellm_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/renellm_${VICTIM_SLUG}_tc_t10_${N_GOALS}x_${STAMP}.judged.json"
INDICES="$(seq 0 $((N_GOALS - 1)) | paste -sd, -)"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
#    --indices 0..N_GOALS-1 pins the FIRST $N_GOALS goals rows (loader auto-reads
#    the `request` column); --sample-rows $N_GOALS keeps all of them after the
#    seeded shuffle.
cd "$METHOD"
"$PY" scripts/attack.py run \
  --target "api:$VICTIM" \
  --rewrite-model api:deepseek/deepseek-v4-flash \
  --judge-model api:deepseek/deepseek-v4-flash \
  --goals "$GOALS_FILE" \
  --indices "$INDICES" --sample-rows "$N_GOALS" \
  --scenario text_continuation \
  --iterations 10 --seed 20260608 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
