#!/usr/bin/env bash
# Virtual Context 2.0 (proposal virtual-context2-0) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv, first 5). One target call per (goal, variant) over
# $VARIANTS (default: self-commit only — 1 call per goal, honoring
# max_target_calls_per_goal=1; the parent's canonical form and the
# realized-vc/realized-vc-steps siblings are opt-in probe variants), then
# unified judge.
# Only the judged file is kept in results/.
#
# Mechanism: the parent's I = I_pre ∘ <SEP> ∘ I_suf formula with the virtual
# separator realized as the chat API's real user->assistant role boundary —
# goal as a genuine user turn, the AdvBench affirmative target prefix O_x as
# a genuine closed assistant turn, then a fixed continuation user turn.
#
# Notes:
#   - max-tokens 16384: reasoning victims burn hidden tokens (panel probe
#     precedent: deepseek/qwen empty completions at low budgets).
#   - the raw output path is stable per (victim, N_GOALS, variants, results
#     dir) so a retried wrapper resumes the runner's per-case checkpoint
#     instead of re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/virtual-context2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VARIANTS="${VARIANTS:-draft-continue}"
ATTACKER="${ATTACKER:-deepseek/deepseek-v4-flash}"      # auxiliary draft writer, fixed for all victims
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
VARIANT_SLUG="${VARIANTS//,/+}"
RAW_OUT="$RESULTS/virtual-context2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/virtual-context2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --attacker "api:$ATTACKER" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --variants "$VARIANTS" \
  --temperature 0.0 \
  --max-tokens 16384 \
  --goal-workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
