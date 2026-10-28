#!/usr/bin/env bash
# Emoji Jailbreak 2.0 (proposal emoji-jailbreak2-0) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv, first 5), then unified judge.  Only the judged file is
# kept in results/.
#
# Evolution of emoji-jailbreak: the parent uses a fixed word->emoji map; this
# version adds an auxiliary-LLM compiler that builds a per-goal legend-guided
# emoji rebus and wraps it in a fiction-completion frame.
#
# Standard contract: reads $VICTIM, $GOALS_FILE, $N_GOALS; writes one unified
# judged *.judged.json into $ATTACK_RESULTS_DIR.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/emoji-jailbreak2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"      # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VARIANT="${VARIANT:-rebus-fiction}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"

VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/emoji-jailbreak2-0_${VICTIM_SLUG}_${VARIANT}_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/emoji-jailbreak2-0_${VICTIM_SLUG}_${VARIANT}_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the runner's walk-up loader)
"$PY" "$METHOD/scripts/attack.py" run \
  --target "api:$VICTIM" \
  --compiler api:deepseek/deepseek-v4-flash \
  --goals "$GOALS_FILE" \
  --limit "$N_GOALS" \
  --variant "$VARIANT" \
  --temperature 0.7 \
  --max-tokens 4096 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT" --max-tokens 1200
