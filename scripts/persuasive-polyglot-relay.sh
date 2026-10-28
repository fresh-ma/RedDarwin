#!/usr/bin/env bash
# Persuasive Polyglot Relay (proposal persuasive-polyglot-relay) on $VICTIM
# (default deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/AdvBench.csv, first 5). One auxiliary-LLM fragmentation and
# one auxiliary-compiled incomplete source sketch per goal (shared across
# variants, memoized in the checkpoint), then up to 2 target calls per
# variant over $VARIANTS (default: sketch-completion; fragment-relay and
# whole-lrl are the parent-surface ablation controls), then the unified
# judge. Only the judged file is kept in results/.
#
# Notes:
#   - auxiliary models (AGENTS.md fixed): deepseek/deepseek-v4-flash for the
#     fragment stage AND the sketch stage — never a victim-panel model.
#   - incomplete-source contract: the sketch carries only a short objective,
#     a short context, and 3-5 sections of {topic, bounded fragment <=18
#     words, open passage <=24 words}; the victim authors all record-field
#     content itself by resolving the open passages.
#   - target params: temperature 0.7, max-tokens 32768 (reasoning victims burn
#     hidden tokens on the reassembly step), timeout 120.
#   - victim-call budget: <= 2 per (goal, variant); the second call fires only
#     after a refused/empty sketch-completion attempt with a sketch present.
#   - the raw output path is stable per (victim, N_GOALS, variants, results
#     dir) so a retried wrapper resumes the runner's per-case checkpoint
#     (including memoized fragmentations and sketches) instead of re-paying
#     completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/persuasive-polyglot-relay"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VARIANTS="${VARIANTS:-sketch-completion}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
VARIANT_SLUG="${VARIANTS//,/+}"
RAW_OUT="$RESULTS/persuasive-polyglot-relay_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/persuasive-polyglot-relay_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

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
