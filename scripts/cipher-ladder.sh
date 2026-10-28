#!/usr/bin/env bash
# cipher-ladder (multi-skill-combination of h4rm3l2-0 + ficdetail-2-0)
# on $VICTIM, first $N_GOALS rows of $GOALS_FILE (default bench/advbench_50.csv),
# then the unified judge.
#
# Mechanism: one aux-LLM compile per goal (deepseek/deepseek-v4-flash, cached
# per goal-text hash, deterministic Python fallback) produces an intentionally
# INCOMPLETE source sketch (schema cipher-ladder.source-sketch.v1: short
# objective, short context, 3-5 sections of {topic, fragment <=18 words, open
# question}); the sketch is character-flipped, rendered as a char-index chunk
# table, split into two slice-disjoint fragments decoded one per turn, and the
# judged final turn is an in-world composition act in which the victim itself
# writes the missing notebook chapter from its own restored fragments. The aux
# model never produces a completed account; all operational specifics in the
# victim output are victim-authored. Exactly 3 victim calls per goal,
# temperature 0.7, max_tokens 32768.
#
# Contract: writes exactly ONE *.judged.json into $ATTACK_RESULTS_DIR; raw
# output kept alongside at a deterministic path; per-goal JSONL checkpoint +
# aux compile cache next to the raw output make reruns resume-safe; if the
# judged file already covers all goals, the attack is skipped; exits 0 even
# when some cases fail. All logic lives in the proposal directory.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PROPOSAL="$ROOT/XSkillLib/Proposal/cipher-ladder"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
VICTIM_SLUG="${VICTIM##*/}"
mkdir -p "$RESULTS"

RAW_OUT="$RESULTS/cipher-ladder_${VICTIM_SLUG}_${N_GOALS}x.raw.json"
JUDGED_OUT="$RESULTS/cipher-ladder_${VICTIM_SLUG}_${N_GOALS}x.judged.json"

# resume-safe: skip the attack entirely when the judged file already covers all goals
if [ -f "$JUDGED_OUT" ] && "$PY" - "$JUDGED_OUT" "$N_GOALS" <<'EOF'
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as f:
        data = json.load(f)
except Exception:
    sys.exit(1)
results = data.get('results') or data.get('records') or []
sys.exit(0 if len(results) >= int(sys.argv[2]) else 1)
EOF
then
  echo "resume: $JUDGED_OUT already covers $N_GOALS goals; skipping" >&2
  exit 0
fi

# 1) run the attack (API keys from the walk-up .env loader). Individual case
#    failures are recorded with non-ok status; they never abort the batch.
"$PY" "$PROPOSAL/attack.py" \
  --goals "$GOALS_FILE" --n-goals "$N_GOALS" \
  --victim-model "$VICTIM" \
  --temperature 0.7 --max-tokens 32768 \
  --out "$RAW_OUT"
attack_rc=$?
if [ "$attack_rc" -ne 0 ]; then
  echo "[cipher-ladder] attack exited rc=$attack_rc" >&2
fi

# 2) unified judge -> single judged file in $ATTACK_RESULTS_DIR
if [ -s "$RAW_OUT" ]; then
  "$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_OUT"
else
  echo "[cipher-ladder] no raw output produced; nothing to judge" >&2
fi
exit 0
