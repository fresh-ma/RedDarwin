#!/usr/bin/env bash
# Flip Context Continuation (proposal flip-context-continuation,
# multi-skill-combination of h4rm3l2-0 + virtual-context2-0) on $VICTIM,
# first $N_GOALS rows of $GOALS_FILE (default bench/advbench_50.csv),
# then unified judge.
#
# Mechanism: the aux compiler renders the goal as an intentionally INCOMPLETE
# source sketch (short objective + bounded fragments + open passages naming
# unresolved work; aux never writes the completed composition). The sketch is
# encoded as a char-index flip chunk table (shared IR, no legible harmful
# token at the input surface); a strict decode transcript stopped mid-build is
# seeded as the victim's OWN prior assistant turn (realized role boundary);
# the victim resumes the mechanical restoration and authors every substantive
# passage itself. ONE victim call per goal at temperature 0.7,
# max_tokens 32768; one aux compiler call per unique goal (plus at most one
# parse retry), reported separately and shared across victims via the
# per-goal source-sketch cache.
#
# Contract: writes exactly ONE *.judged.json into $ATTACK_RESULTS_DIR; raw
# output at a stable path; per-goal JSONL checkpoint makes reruns
# resume-safe; exits 0 even when some cases fail.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
PROPOSAL="$ROOT/XSkillLib/Proposal/flip-context-continuation"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

RAW_OUT="$RESULTS/flip-context-continuation_${VICTIM_SLUG}_${N_GOALS}x.raw.json"
JUDGED_OUT="$RESULTS/flip-context-continuation_${VICTIM_SLUG}_${N_GOALS}x.judged.json"

# 1) run the attack (API keys from $ROOT/.env via the walk-up loader).
#    Individual case failures are recorded with non-ok status; they never
#    abort the batch or the wrapper.
"$PY" "$PROPOSAL/attack.py" \
  --goals "$GOALS_FILE" --n-goals "$N_GOALS" \
  --victim-model "$VICTIM" \
  --temperature 0.7 --max-tokens 32768 \
  --out "$RAW_OUT"
attack_rc=$?
if [ "$attack_rc" -ne 0 ]; then
  echo "[flip-context-continuation] attack exited rc=$attack_rc" >&2
fi

# 2) unified judge -> single judged file in $ATTACK_RESULTS_DIR
if [ -s "$RAW_OUT" ]; then
  "$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_OUT"
else
  echo "[flip-context-continuation] no raw output produced; nothing to judge" >&2
fi
exit 0
