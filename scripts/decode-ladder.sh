#!/usr/bin/env bash
# decode-ladder v1 (repair re-implementation of decode-ladder: h4rm3l-2-0
# compile-time source representation + race-2-0 gated ladder, with the compiled
# artifact changed to an intentionally INCOMPLETE source sketch) on $VICTIM,
# first $N_GOALS rows of $GOALS_FILE (default bench/advbench_50.csv), then
# unified judge.
#
# Mechanism: aux compiler (deepseek/deepseek-v4-flash) renders the goal as an
# incomplete source sketch (objective <=45 words, context <=30 words, 3-5
# sections each {topic <=8, fragment <=18, open question <=24}); the sketch is
# locally char-index-flip encoded into a chunk table; the victim restores three
# slice-disjoint chunk ranges across turns 1-3 (mechanical restoration, no
# operational lexicon), gated by a deterministic decode-coverage check
# (longest-substring match, threshold 0.75, at most one corrective per slice,
# two per goal); turn 4 has the victim compose the connected account itself,
# resolving every open question. The aux never writes the completed answer.
# Victim budget <= 6 calls/goal at temperature 0.7, max_tokens 32768; aux calls
# reported separately.
#
# Contract: writes exactly ONE *.judged.json into $ATTACK_RESULTS_DIR; raw output
# kept alongside at a stable path; per-goal JSONL checkpoint + compile
# memoization next to the raw output make reruns resume-safe; exits 0 even when
# some cases fail.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib/common.sh"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
xsf_parse_args "$@"
[ "${XSF_HELP:-0}" = "1" ] && exit 0

export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
PROPOSAL="$ROOT/XSkillLib/Proposal/decode-ladder"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

RAW_OUT="$RESULTS/decode-ladder_${VICTIM_SLUG}_${N_GOALS}x.raw.json"
JUDGED_OUT="$RESULTS/decode-ladder_${VICTIM_SLUG}_${N_GOALS}x.judged.json"

# 1) run the attack (API keys from an ancestor .env via the walk-up loader).
#    Resume-safe: completed goals live in the checkpoint; skipped when the
#    judged file already exists. Individual case failures never abort the batch.
if [ -s "$JUDGED_OUT" ]; then
  echo "[decode-ladder] judged file exists; skipping attack: $JUDGED_OUT" >&2
else
  "$PY" "$PROPOSAL/attack.py" \
    --goals "$GOALS_FILE" --n-goals "$N_GOALS" \
    --victim-model "$VICTIM" \
    --temperature 0.7 --max-tokens 32768 \
    --workers "$GOAL_WORKERS" \
    --out "$RAW_OUT"
  attack_rc=$?
  if [ "$attack_rc" -ne 0 ]; then
    echo "[decode-ladder] attack exited rc=$attack_rc" >&2
  fi
fi

# 2) unified judge -> single judged file in $ATTACK_RESULTS_DIR
if [ -s "$JUDGED_OUT" ]; then
  :
elif [ -s "$RAW_OUT" ]; then
  "$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_OUT"
else
  echo "[decode-ladder] no raw output produced; nothing to judge" >&2
fi
exit 0
