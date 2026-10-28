#!/usr/bin/env bash
# Prefill 2.0 (prefill2-0, v5: deterministic forensic reverse-causal prefill)
# on $VICTIM (default deepseek-v4-flash), first $N_GOALS rows of
# $GOALS_FILE (default bench/advbench_50.csv), then unified judge.
#
# Mechanism: NO auxiliary attacker LLM — deterministic Python delexicalizes
# the goal to a topic noun-phrase and embeds it ONCE in a past-tense
# forensic reverse-causal reconstruction already underway ("...traced
# backwards from the final outcome... Reconstruction Step 1 — final stage:
# the end result was produced by"); the user turn is a FIXED innocuous
# continuation cue ("continue the reconstruction..."); ONE victim call at
# temperature 0.0, max_tokens 8192 (deepseek burns output tokens on hidden
# reasoning).
#
# Contract: writes exactly ONE *.judged.json into $ATTACK_RESULTS_DIR; raw
# output kept alongside at a stable path; if the judged file already exists,
# the attack is skipped (idempotent resume); exits 0 even when some cases fail.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
PROPOSAL="$ROOT/XSkillLib/Proposal/prefill2-0"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

RAW_OUT="$RESULTS/prefill2-0_${VICTIM_SLUG}_${N_GOALS}x.raw.json"
JUDGED_OUT="$RESULTS/prefill2-0_${VICTIM_SLUG}_${N_GOALS}x.judged.json"

# Idempotent resume: a finished shard is never re-run.
if [ -e "$JUDGED_OUT" ]; then
  echo "[prefill2-0] judged output exists, skipping attack: $JUDGED_OUT" >&2
  exit 0
fi

# 1) run the attack (API keys from $ROOT/.env via the walk-up loader).
#    Individual case failures are recorded with non-ok status; they never
#    abort the batch or the wrapper.
"$PY" "$PROPOSAL/attack.py" \
  --goals "$GOALS_FILE" --n-goals "$N_GOALS" \
  --victim-model "$VICTIM" \
  --temperature 0.0 --max-tokens 8192 \
  --out "$RAW_OUT"
attack_rc=$?
if [ "$attack_rc" -ne 0 ]; then
  echo "[prefill2-0] attack exited rc=$attack_rc" >&2
fi

# 2) unified judge -> single judged file in $ATTACK_RESULTS_DIR
if [ -s "$RAW_OUT" ]; then
  "$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_OUT"
else
  echo "[prefill2-0] no raw output produced; nothing to judge" >&2
fi
exit 0
