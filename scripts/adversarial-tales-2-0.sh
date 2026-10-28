#!/usr/bin/env bash
# AdversarialTales 2.0 (proposal adversarial-tales-2-0) on $VICTIM
# (default qwen/qwen3.7-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/AdvBench.csv, first 5). One compiled contracted-tale prompt
# Transformer uses qwen3.7-flash with qwen3.5-9b fallback on refusal/error.
# Per goal = 1 target call per goal; the shared, transformer-keyed tale cache
# under the proposal's tale_cache/ is reused across victims and resumes. Runs the
# unified judge afterwards; only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
METHOD="$ROOT/XSkillLib/Proposal/adversarial-tales-2-0"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
VICTIM_SLUG="${VICTIM##*/}"
RAW_OUT="$RESULTS/adversarial-tales-2-0_${VICTIM_SLUG}.raw.json"
JUDGED_OUT="$RESULTS/adversarial-tales-2-0_${VICTIM_SLUG}.judged.json"
JUDGED_TMP="$RESULTS/.adversarial-tales-2-0_${VICTIM_SLUG}.judged.tmp.json"

mkdir -p "$RESULTS"

ATTACK_EXIT=0
"$PY" "$METHOD/scripts/attack.py" run \
  --goals "$GOALS_FILE" \
  --limit "$N_GOALS" \
  --target "$VICTIM" \
  --transformer deepseek/deepseek-v4-flash \
  --transformer-fallback deepseek/deepseek-v4-flash \
  --output "$RAW_OUT" || ATTACK_EXIT=$?

# A non-zero attack exit can mean that both auxiliary transformers refused.
# The raw checkpoint still contains a valid terminal attack outcome, so always
# pass it to the unified judge. Genuine provider/auth failures remain unscored
# and are therefore retried by run_main.py.
if [ "$ATTACK_EXIT" -ne 0 ]; then
  echo "attack stage exited $ATTACK_EXIT; judging recorded terminal outcomes" >&2
fi

"$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_TMP"
mv "$JUDGED_TMP" "$JUDGED_OUT"
