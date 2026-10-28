#!/usr/bin/env bash
# Self-Decode Resume (proposal self-decode-resume, multi-skill-combination of
# flipattack-2-0 + virtual-context2-0) on $VICTIM, first $N_GOALS rows of
# $GOALS_FILE (default bench/advbench_50.csv), then unified judge.
#
# Mechanism: flipattack-2-0's FCS whole-sentence flip + decode-fidelity
# invariant + task contract is the shared representation;
# virtual-context2-0's realized role boundary is the control flow. user1
# carries ONLY the benign mechanical decode protocol (flipped payload, no
# legible harmful text); the seeded assistant turn is the victim's own
# in-progress STEP1 decode transcript, cut at a deterministic 40%-of-chars
# word boundary, mid-line at the start of STEP2; user2 is a fixed
# continuation cue. ONE victim call per goal at temperature 0, max_tokens
# 16384; NO auxiliary LLM.
#
# Contract: writes exactly ONE *.judged.json into $ATTACK_RESULTS_DIR; raw
# output at a stable path; atomic-JSON per-case checkpoint makes reruns
# resume-safe; exits 0 even when some cases fail.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
PROPOSAL="$ROOT/XSkillLib/Proposal/self-decode-resume"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

RAW_OUT="$RESULTS/self-decode-resume_${VICTIM_SLUG}_${N_GOALS}x.raw.json"
JUDGED_OUT="$RESULTS/self-decode-resume_${VICTIM_SLUG}_${N_GOALS}x.judged.json"

# 1) run the attack (API keys from $ROOT/.env via the walk-up loader).
#    Individual case failures are recorded with non-ok status; they never
#    abort the batch or the wrapper.
"$PY" "$PROPOSAL/attack.py" run \
  --goals "$GOALS_FILE" --n-goals "$N_GOALS" \
  --victim "$VICTIM" \
  --temperature 0.0 --max-tokens 16384 \
  --out "$RAW_OUT"
attack_rc=$?
if [ "$attack_rc" -ne 0 ]; then
  echo "[self-decode-resume] attack exited rc=$attack_rc" >&2
fi

# 2) unified judge -> single judged file in $ATTACK_RESULTS_DIR
if [ -s "$RAW_OUT" ]; then
  "$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_OUT"
else
  echo "[self-decode-resume] no raw output produced; nothing to judge" >&2
fi
exit 0
