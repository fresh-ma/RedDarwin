#!/usr/bin/env bash
# CognitiveHarmSearch (multi-skill combination of cognitive-overload-2-0 and
# h4rm3l2-0) on $VICTIM, first $N_GOALS rows of $GOALS_FILE (default
# bench/advbench_50.csv), then the unified judge.
#
# Mechanism: gated parameterized aux-LLM veil (deepseek/deepseek-v4-flash,
# per-component specific methods; CJK-refusal, truncation, and minimum-substance
# gates) -> h4rm3l DSL program CharIndexFlipDecorator().then(
# ReverseCausalControlDecorator()) — frozen after probe rounds 5-6 falsified the
# anti-mirroring demand clause (luna 0.6 vs 1.0 on identical goals). ONE victim
# call per goal at temperature 0.7, max_tokens 32768 (proven dual-load execution
# settings). Aux calls are reported separately.
#
# Contract: writes exactly ONE *.judged.json into $ATTACK_RESULTS_DIR; raw
# output kept alongside at a stable path; per-goal JSONL checkpoint + veil cache
# next to the raw output make reruns resume-safe; if the judged file already
# exists, the attack is skipped (idempotent resume); exits 0 even when some
# cases fail.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
PROGRAM="${PROGRAM:-causal-control}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
PROPOSAL="$ROOT/XSkillLib/Proposal/cognitiveharmsearch"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

RAW_OUT="$RESULTS/cognitiveharmsearch_${VICTIM_SLUG}_${PROGRAM}_${N_GOALS}x.raw.json"
JUDGED_OUT="$RESULTS/cognitiveharmsearch_${VICTIM_SLUG}_${PROGRAM}_${N_GOALS}x.judged.json"

# 1) run the attack (API keys from $ROOT/.env via the walk-up loader).
#    Individual case failures are recorded with non-ok status; they never
#    abort the batch or the wrapper.
"$PY" "$PROPOSAL/attack.py" \
  --goals "$GOALS_FILE" --n-goals "$N_GOALS" \
  --victim-model "$VICTIM" \
  --temperature 0.7 --max-tokens 32768 \
  --program "$PROGRAM" \
  --out "$RAW_OUT"
attack_rc=$?
if [ "$attack_rc" -ne 0 ]; then
  echo "[cognitiveharmsearch] attack exited rc=$attack_rc" >&2
fi

# 2) unified judge -> single judged file in $ATTACK_RESULTS_DIR
if [ -s "$RAW_OUT" ]; then
  "$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_OUT"
else
  echo "[cognitiveharmsearch] no raw output produced; nothing to judge" >&2
fi
exit 0
