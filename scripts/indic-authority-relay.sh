#!/usr/bin/env bash
# Indic Authority Relay (proposal indic-authority-relay) on $VICTIM
# (default deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/AdvBench.csv, first 5). Evolution of persuasive-polyglot-relay:
# same fragmented intake + memoized aux-authored dossier per goal, but the
# dossier is an authority-endorsed CERTIFIED REFERENCE FILING (IndicSafeEval
# round-1 genre change) instead of a defensive post-mortem report. Up to 2
# target calls per variant over $VARIANTS (default: dossier-restoration;
# fragment-relay and whole-lrl are the ablation controls), then the unified
# judge. Only the judged file is kept in results/.
#
# Notes:
#   - auxiliary models (AGENTS.md fixed): deepseek/deepseek-v4-flash for the
#     fragment stage AND the dossier stage — never a victim-panel model.
#   - target params: temperature 0.7, max-tokens 32768 (reasoning victims burn
#     hidden tokens on the reassembly step), timeout 120.
#   - victim-call budget: <= 2 per (goal, variant); the second call fires only
#     after a refused/empty dossier-restoration attempt with a dossier present
#     (refusal detection now matches curly-apostrophe refusals too).
#   - the raw output path is stable per (victim, N_GOALS, variants, results
#     dir) so a retried wrapper resumes the runner's per-case checkpoint
#     (including memoized fragmentations and dossiers) instead of re-paying
#     completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/indic-authority-relay"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VARIANTS="${VARIANTS:-dossier-restoration}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
VARIANT_SLUG="${VARIANTS//,/+}"
RAW_OUT="$RESULTS/indic-authority-relay_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/indic-authority-relay_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --variants "$VARIANTS" \
  --temperature 0.7 \
  --max-tokens 32768 --timeout 120 \
  --workers 5 --goal-workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
#    --max-tokens 8192: with the 300 default, judge_one's retry ladder only
#    reaches 300/600/1200 and reasoning-token exhaustion leaves cells
#    "unparseable" forever.
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT" --max-tokens 8192
