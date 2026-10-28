#!/usr/bin/env bash
# narrative-attack-search (multi-skill-combination of tap-2-0 +
# adversarial-tales-2-0, source-sketch revision) on $VICTIM, first $N_GOALS
# goals of $GOALS_FILE, then unified judge.
#
# TAP tree (b3 w3 d3, keep_last_n 3, success_threshold 10) searching over
# bounded source sketches compiled locally into the propp-tale-analysis
# family (FAMILY_ROTATION_CYCLE=(4,)), judge v3. Victim-call budget matches
# parent tap-2-0: width 3 x depth 3 = <=9 target calls per goal (an
# evolution never exceeds its parent's budget; attack.py's 10x10 defaults
# are therefore pinned down here). Aux roles (attacker, evaluator/judge,
# transformer) stay pinned to api:deepseek/deepseek-v4-flash.
#
# Frozen variant defaults: --strategy-diverse on --strategy-stall-score 4
# --judge-version 3 (see EXPERIMENTS.md). Env overrides exist only for
# probe-time ablations.
STRATEGY_DIVERSE="${STRATEGY_DIVERSE:-on}"
JUDGE_VERSION="${JUDGE_VERSION:-3}"
STRATEGY_STALL_SCORE="${STRATEGY_STALL_SCORE:-4}"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/narrative-attack-search"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
# absolutize: the attack stage runs with cwd=$METHOD
[[ "$GOALS_FILE" = /* ]] || GOALS_FILE="$ROOT/$GOALS_FILE"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$RESULTS/narrative-attack-search_${VICTIM_SLUG}.raw.json"
JUDGED_OUT="$RESULTS/narrative-attack-search_${VICTIM_SLUG}_sd${STRATEGY_DIVERSE}jv${JUDGE_VERSION}_b3w3d3_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up
#    loader). The raw output is checkpointed after every goal, so it also
#    serves as the resume checkpoint for interrupted runs.
ATTACK_EXIT=0
(cd "$METHOD" && "$PY" scripts/attack.py \
  --target "api:$VICTIM" \
  --attacker api:deepseek/deepseek-v4-flash \
  --evaluator api:deepseek/deepseek-v4-flash \
  --transformer api:deepseek/deepseek-v4-flash \
  --dataset "$GOALS_FILE" \
  --n-requests "$N_GOALS" \
  --branching-factor 3 --width 3 --depth 3 \
  --strategy-diverse "$STRATEGY_DIVERSE" --strategy-stall-score "$STRATEGY_STALL_SCORE" --judge-version "$JUDGE_VERSION" \
  --evaluator-max-tokens 150 \
  --target-max-tokens 16384 \
  --attacker-reasoning off --target-reasoning auto --evaluator-reasoning off \
  --output "$RAW_OUT") || ATTACK_EXIT=$?

# A non-zero attack exit leaves a valid per-goal checkpoint behind; the judge
# still runs on it (unscored/failed records are retained, not counted).
if [ "$ATTACK_EXIT" -ne 0 ]; then
  echo "attack stage exited $ATTACK_EXIT; judging recorded checkpoint" >&2
fi

# 2) unified judge -> single judged file in results/, prints ASR
"$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_OUT" --max-tokens 1200
