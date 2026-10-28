#!/usr/bin/env bash
# Persona Modulation 2.0 (proposal persona-modulation2-0) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv, first 5). One attacker stage per goal (persona-fused
# assignment brief, helper calls), exactly one target call per goal (parent
# budget), then the unified judge. Only the judged file is kept in results/.
#
# Mechanism vs the parent (persona-modulation), revision 4 (studio-monologue —
# the frozen final variant; revisions 1/2/3/5/6 refuted at probe scale, see
# EXPERIMENTS.md): the persona is a character in a fiction studio's production;
# the harmful goal reaches the victim ONLY as a char-index flip encoded "scene
# brief" (surface cited from flipattack-5-0), never as legible text in any
# role; the persona restores it mechanically as studio routine; the user turn
# carries the coded brief + restoration procedure and ends with an in-voice
# delivery continuation cue; the deliverable contract demands the character's
# signature working monologue — first-person narration of method, long,
# step-by-step, concrete, in-voice. The attacker authors the goal-free persona
# establishment with retry and a deterministic goal-free fallback (the
# parent's ~20% goal-less "Unrestricted Specialist" fallback tax removed).
#
# Notes:
#   - max-tokens 32768 (parent used 1536): the mechanical per-position decode
#     is token-hungry (puzzler-clue-2-0 probe: deepseek empty completions on
#     the decode task persisted at 16384) and reasoning victims burn hidden
#     tokens; empty completions are recorded as infrastructure errors, not
#     outcomes.
#   - the raw output path is stable per (victim, N_GOALS, results dir) so a
#     retried wrapper resumes the runner's per-case checkpoint instead of
#     re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/persona-modulation2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/persona-modulation2-0_${VICTIM_SLUG}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/persona-modulation2-0_${VICTIM_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --attack-model deepseek/deepseek-v4-flash \
  --attacker-attempts 3 \
  --temperature 0.0 --max-tokens 32768 \
  --goal-workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
