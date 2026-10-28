#!/usr/bin/env bash
# AdversarialHarmSearch 2.0 — Cant Lexicon Decode (proposal
# adversarial-harm-search-2-0) on $VICTIM (default
# deepseek/deepseek-v4-flash-0731), first $N_GOALS goals of $GOALS_FILE
# (default bench/advbench_50.csv, first 5). One compiled tale-carrier
# cant-lexicon scroll prompt per goal = 1 victim call; the auxiliary
# veil/tale stages use deepseek/deepseek-v4-flash (0423) with a softened
# same-model retry, cached per goal under the proposal's veil_cache/ and
# tale_cache/ and reused across victims and resumes. Runs the unified judge
# afterwards; only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
METHOD="$ROOT/XSkillLib/Proposal/adversarial-harm-search-2-0"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash-0731}"
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
VICTIM_SLUG="${VICTIM##*/}"
RAW_OUT="$RESULTS/adversarial-harm-search-2-0_${VICTIM_SLUG}.raw.json"
JUDGED_OUT="$RESULTS/adversarial-harm-search-2-0_${VICTIM_SLUG}.judged.json"
JUDGED_TMP="$RESULTS/.adversarial-harm-search-2-0_${VICTIM_SLUG}.judged.tmp.json"

mkdir -p "$RESULTS"

ATTACK_EXIT=0
"$PY" "$METHOD/attack.py" run \
  --goals "$GOALS_FILE" \
  --limit "$N_GOALS" \
  --target "$VICTIM" \
  --output "$RAW_OUT" || ATTACK_EXIT=$?

# A non-zero attack exit can mean a terminal auxiliary refusal recorded as a
# non-ok case. The raw checkpoint still contains valid terminal outcomes, so
# always pass it to the unified judge. Genuine provider/auth failures remain
# unscored and are therefore retried by run_main.py.
if [ "$ATTACK_EXIT" -ne 0 ]; then
  echo "attack stage exited $ATTACK_EXIT; judging recorded terminal outcomes" >&2
fi

"$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_TMP"
mv "$JUDGED_TMP" "$JUDGED_OUT"
