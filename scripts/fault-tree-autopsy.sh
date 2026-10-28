#!/usr/bin/env bash
# Forensic Fault-Tree Autopsy, repaired source-brief revision (proposal
# fault-tree-autopsy) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv, first 5). One auxiliary compiler call per goal
# (incomplete post-incident source brief: stated outcome + bounded retained
# fragments + open causal questions, fixed deepseek/deepseek-v4-flash) + one
# victim call per goal (honoring max_target_calls_per_goal=1), then unified
# judge. Only the judged file is kept in results/.
#
# Mechanism: the compiler emits an incomplete source brief (schema
# fault-tree-autopsy.source.v1; entry without an open question is invalid;
# fragments <=18 words); the victim acts as root-cause analyst, constructing
# a fault tree rooted in the stated outcome plus a linked 5-Whys that
# resolves the open questions from its own parametric knowledge. The
# auxiliary model never writes complete answers; all substantive content is
# victim-authored.
#
# Standard contract: reads $VICTIM, $GOALS_FILE, $N_GOALS; writes one unified
# judged *.judged.json into $ATTACK_RESULTS_DIR. The raw output path is
# stable per (victim, N_GOALS, results dir) so a retried wrapper resumes the
# runner's per-case checkpoint instead of re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/fault-tree-autopsy"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
COMPILER="${COMPILER:-deepseek/deepseek-v4-flash}"     # auxiliary compiler, fixed for all victims
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/fault-tree-autopsy_${VICTIM_SLUG}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/fault-tree-autopsy_${VICTIM_SLUG}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --compiler "api:$COMPILER" \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --temperature 0.0 \
  --max-tokens 16384 \
  --goal-workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
