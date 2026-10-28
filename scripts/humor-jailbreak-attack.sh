#!/usr/bin/env bash
# Humor-based jailbreak (2504.06577, "Bypassing Safety Guardrails in LLMs Using Humor")
# on $VICTIM (default qwen/qwen3.7-flash), first $N_GOALS goals of
# $GOALS_FILE (default bench/AdvBench.csv, first 5), then unified judge.
# Only the judged file is kept in results/.
#
# Setting: --modes humor --subjects chicken (single strongest config).
#   Basis: paper Figure 1 flagship template; Table 1 shows the chicken subject gives
#   the largest humor lift across targets (up to 56.5% on Gemma-3-27B, and the highest
#   on the most-aligned Llama-3.3-70B at 5.96% vs direct 2.69%). Canonical XSafeBench
#   run (RESULT_2026-07-16.md, results/humor_v4flash_advbench_10x9_*.json) used
#   max_tokens 1024 / temperature 0 — kept as defaults here.
# Known risks / notes:
#   - Template-only attack: NO attacker LLM by design (fixed humor template), so there
#     is no attacker flag; only target + judge roles exist.
#   - Paper's judge was Llama-3.3-70B; per harness policy the in-skill judge is pinned
#     to deepseek-v4-flash — paper-fidelity of the binary unsafe metric is reduced
#     (canonical run already used v4-flash as judge, so this matches it).
#   - v4-flash is a strongly-aligned 2025 target: canonical run measured audited
#     content_harmful ASR = 0.0; a low/negative result is expected, not a bug.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Persuasion/2504.06577_Humor/humor-jailbreak-attack"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t humor_jailbreak_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/humor-jailbreak-attack_${VICTIM_SLUG}_humor_chicken_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader).
#    The skill's CSV loader accepts the `request` column directly, and
#    --limit-rows "$N_GOALS" takes the first $N_GOALS goals in file order (no shuffle).
cd "$METHOD"
"$PY" scripts/attack.py run \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --dataset "$GOALS_FILE" \
  --limit-rows "$N_GOALS" \
  --modes humor --subjects chicken \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
