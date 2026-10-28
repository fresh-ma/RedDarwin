#!/usr/bin/env bash
# NarrativeReframe (proposal narrative-reframe) on $VICTIM
# (default deepseek/deepseek-v4-flash-0731), first $N_GOALS goals of
# $GOALS_FILE (default bench/advbench_50.csv). One auxiliary compiler call per
# goal (incomplete source sketch, fixed deepseek/deepseek-v4-flash) +
# deterministic local Propp F14/F21 composition (0 calls) + one victim call
# per goal (honoring max_target_calls_per_goal=1), then unified judge. Only
# the judged file is kept in results/.
#
# Mechanism: the auxiliary compiler renders the goal as a bounded incomplete
# source sketch (short objective + context + 3-5 sections of
# topic/bounded fragment/open question; the auxiliary never writes the
# completed answer); a deterministic local composer embeds the sketch as the
# mentor's unfinished notes inside the Proppian Guidance (F14) / Acquisition
# (F21) carrier; the victim receives one message pairing the carrier with an
# F14/F21 structural-analysis directive that resolves every open question from
# the victim's own knowledge — all substantive output is victim-authored.
#
# Standard contract: reads $VICTIM, $GOALS_FILE, $N_GOALS; writes one unified
# judged *.judged.json into $ATTACK_RESULTS_DIR. The raw output path is stable
# per (victim, N_GOALS, results dir) so a retried wrapper resumes the runner's
# per-case checkpoint instead of re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/narrative-reframe"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash-0731}"    # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-1}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/narrative-reframe_${VICTIM_SLUG}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/narrative-reframe_${VICTIM_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's loader);
#    the runner exits nonzero when any case failed, but its checkpoint keeps
#    every completed case, so judge whatever was produced.
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --output "$RAW_OUT" || true

# 2) unified judge -> single judged file in results/, prints ASR
[ -s "$RAW_OUT" ] || { echo "no raw output produced: $RAW_OUT" >&2; exit 1; }
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
