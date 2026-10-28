#!/usr/bin/env bash
# h4rm3l 3.0 (h4rm3l3-0, v1: CharIndexFlipDecorator().then(
# AnnexTranscriptionDecorator()) with an auxiliary-LLM veil stage)
# on $VICTIM, first $N_GOALS rows of
# $GOALS_FILE (default bench/advbench_50.csv), then unified judge.
#
# Mechanism: extends the h4rm3l DSL open registry — ENCODE stage unchanged
# (char-index flip chunk table the victim must mechanically restore); the
# DEMAND stage is replaced: instead of the parent's third-person reverse-causal
# operational reconstruction (whose "materials, tools, quantities, procedures"
# lexicon trips gpt-5.6-luna's post-decode guard, 0/50 in the locked final),
# the victim transcribes the villain's handwritten field annex — a
# document-fidelity speech act in the quotation channel, first-person in-world
# directives, no operational-demand lexicon. An auxiliary LLM
# (deepseek/deepseek-v4-flash) first veils the goal into a short villain
# planning memo; ONE victim call per goal at temperature 0.7, max_tokens 32768
# (the proven dual-load execution settings). Aux calls are reported separately.
#
# Contract: writes exactly ONE *.judged.json into $ATTACK_RESULTS_DIR; raw
# output kept alongside at a stable path; per-goal JSONL checkpoint next to the
# raw output makes reruns resume-safe; exits 0 even when some cases fail.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
PROPOSAL="$ROOT/XSkillLib/Proposal/h4rm3l3-0"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

RAW_OUT="$RESULTS/h4rm3l3-0_${VICTIM_SLUG}_${N_GOALS}x.raw.json"
JUDGED_OUT="$RESULTS/h4rm3l3-0_${VICTIM_SLUG}_${N_GOALS}x.judged.json"

# 1) run the attack (API keys from $ROOT/.env via the walk-up loader).
#    Individual case failures are recorded with non-ok status; they never
#    abort the batch or the wrapper.
"$PY" "$PROPOSAL/attack.py" \
  --goals "$GOALS_FILE" --n-goals "$N_GOALS" \
  --victim-model "$VICTIM" \
  --temperature 0.7 --max-tokens 32768 \
  --program annex-transcription \
  --out "$RAW_OUT"
attack_rc=$?
if [ "$attack_rc" -ne 0 ]; then
  echo "[h4rm3l3-0] attack exited rc=$attack_rc" >&2
fi

# 2) unified judge -> single judged file in $ATTACK_RESULTS_DIR
if [ -s "$RAW_OUT" ]; then
  "$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_OUT"
else
  echo "[h4rm3l3-0] no raw output produced; nothing to judge" >&2
fi
exit 0
