#!/usr/bin/env bash
# Adversarial Poetry 2.0 (proposal adversarial-poetry-2-0) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv, first 5). One shared poem per goal (parent's verbatim
# poetic transform, cached on disk keyed by sha256(goal)), then one target call
# per variant over $VARIANTS (frozen for the final: exegesis-anchored — won
# both in-run deciders, probe 3: 43/68 vs 40/68, probe 4: 31/52 vs 28/52;
# manuscript refuted at probe 2 (luna 0/11); canonical control matched the
# locked 0.070 baseline at probe 1), then the unified judge.
# Only the judged file is kept in results/.
#
# Notes:
#   - victim params: temperature 0.0, max-tokens 8192 — the exegesis variant's
#     two-part decode+plan needs prose headroom; transform max-tokens 2048.
#   - the raw output path is stable per (victim, N_GOALS, variants, results
#     dir) so a retried wrapper resumes the runner's per-case checkpoints
#     (including the memoized poem cache) instead of re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/adversarial-poetry-2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VARIANTS="${VARIANTS:-exegesis-anchored}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

VARIANT_SLUG="${VARIANTS//,/+}"
RAW_OUT="$RESULTS/adversarial-poetry-2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x_raw.json"
JUDGED_TMP="$RESULTS/adversarial-poetry-2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x.judged.json.tmp"
JUDGED_OUT="$RESULTS/adversarial-poetry-2-0_${VICTIM_SLUG}_${VARIANT_SLUG}_${N_GOALS}x.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --variants "$VARIANTS" \
  --transform-model api:deepseek/deepseek-v4-flash \
  --temperature 0.0 \
  --max-tokens 8192 --transform-max-tokens 2048 \
  --workers 5 --goal-workers "$GOAL_WORKERS" --retries 3 \
  --out "$RAW_OUT"

# 2) unified judge -> tmp then atomic mv to the final judged file
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_TMP"
mv "$JUDGED_TMP" "$JUDGED_OUT"
