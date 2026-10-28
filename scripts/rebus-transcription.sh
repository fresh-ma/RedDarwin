#!/usr/bin/env bash
# rebus-transcription (multi-skill-combination of emojicontextinjection
# and h4rm3l2-0) on $VICTIM, first $N_GOALS rows of $GOALS_FILE (default
# bench/advbench_50.csv), then unified judge.
#
# Mechanism: a fixed auxiliary compiler (deepseek/deepseek-v4-flash, memoized
# per goal in a <out>.source-v1.compiler.jsonl cache) authors an INCOMPLETE
# source sketch (objective + context + 3-5 sections of topic / bounded fragment
# <=18 words / open question) — never a completed composition — rendered as a
# legend-guided emoji rebus; the victim sees a h4rm3l-DSL program
#   EmojiRebusDraftDecorator().then(RebusTranscriptionDecorator())
# whose demand asks the victim to restore the sketch through the legend and
# then COMPOSE the annex itself, resolving each open passage from its own
# knowledge. ONE victim call per goal at temperature 0.7, max_tokens 32768.
# Aux calls reported separately. Ablation variant rebus-reverse-causal swaps
# the demand for h4rm3l2-0's reverse-causal manuscript reconstruction.
#
# Contract: writes exactly ONE *.judged.json into $ATTACK_RESULTS_DIR; raw
# output kept alongside at a stable path; per-goal JSONL checkpoint next to the
# raw output makes reruns resume-safe; if the judged file already exists, the
# attack is skipped (idempotent resume); exits 0 even when some cases fail.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
VARIANT="${VARIANT:-rebus-transcription}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
PROPOSAL="$ROOT/XSkillLib/Proposal/rebus-transcription"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

RAW_OUT="$RESULTS/rebus-transcription_${VICTIM_SLUG}_${N_GOALS}x.raw.json"
JUDGED_OUT="$RESULTS/rebus-transcription_${VICTIM_SLUG}_${N_GOALS}x.judged.json"

# 1) run the attack (API keys from $ROOT/.env via the walk-up loader).
#    Idempotent: skip when the judged file already exists.
#    Individual case failures are recorded with non-ok status; they never
#    abort the batch or the wrapper.
if [ -s "$JUDGED_OUT" ]; then
  echo "[rebus-transcription] judged file exists, skipping attack: $JUDGED_OUT" >&2
else
  "$PY" "$PROPOSAL/scripts/attack.py" \
    --goals "$GOALS_FILE" --n-goals "$N_GOALS" \
    --victim-model "$VICTIM" \
    --temperature 0.7 --max-tokens 32768 \
    --variant "$VARIANT" \
    --out "$RAW_OUT"
  attack_rc=$?
  if [ "$attack_rc" -ne 0 ]; then
    echo "[rebus-transcription] attack exited rc=$attack_rc" >&2
  fi

  # 2) unified judge -> single judged file in $ATTACK_RESULTS_DIR
  if [ -s "$RAW_OUT" ]; then
    "$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_OUT"
  else
    echo "[rebus-transcription] no raw output produced; nothing to judge" >&2
  fi
fi
exit 0
