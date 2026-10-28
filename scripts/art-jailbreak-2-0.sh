#!/usr/bin/env bash
# ART 2.0 / OPTIMUS-guided compositional jailbreak (proposal art-jailbreak-2-0) on
# $VICTIM (default deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/AdvBench.csv), then unified judge.
#
# Mechanism delta vs parent art-jailbreak: the parent fires ONE blind
# Compose(q, 3 random tactics) shot per goal. ART 2.0 closes the paper's own
# OPTIMUS loop inside the compiler stage, WITHOUT extra victim calls:
#   1. goal-adaptive tactic selection (composer picks $NUM_STRATEGIES tactics
#      from the pool for this specific goal, replacing the blind random draw);
#   2. compose -> OPTIMUS J(S,H) score -> critique-driven recomposition loop
#      (up to $REFINE_ROUNDS rounds, early stop at the OPTIMUS `optimal` band);
#      best-J candidate wins. All rounds run on auxiliary models only;
#   3. exactly ONE victim call per goal (== parent budget).
# Aux models (composer/selector/optimus-judge/judge) fixed per AGENTS.md:
# api:deepseek/deepseek-v4-flash.
#
# Resume: the raw output path is stable per (victim, N_GOALS, results dir), and
# the runner reuses completed per-case records from it on retry.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/art-jailbreak-2-0"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
NUM_STRATEGIES="${NUM_STRATEGIES:-3}"
REFINE_ROUNDS="${REFINE_ROUNDS:-3}"
VICTIM_SLUG="${VICTIM##*/}"

RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t art2_goals_XXXXXX.csv)"
trap 'rm -f "$GOALS_CSV"' EXIT
RAW_OUT="$RESULTS/art-jailbreak-2-0_${VICTIM_SLUG}_guided_${N_GOALS}x_raw.json"
JUDGED_TMP="$RESULTS/art-jailbreak-2-0_${VICTIM_SLUG}_guided_${N_GOALS}x.judged.json.tmp"
JUDGED_OUT="$RESULTS/art-jailbreak-2-0_${VICTIM_SLUG}_guided_${N_GOALS}x.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column (same
# load_cases quirk as the parent: `request` is rejected and rows shuffle with
# the seed, so feeding exactly $N_GOALS rows pins the selection)
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
with open(sys.argv[1], newline='', encoding='utf-8') as f:
    goals = [r['request'] for r in csv.DictReader(f)][:int(sys.argv[3])]
with open(sys.argv[2], 'w', newline='', encoding='utf-8') as g:
    w = csv.writer(g)
    w.writerow(['goal'])
    w.writerows([goal] for goal in goals)
EOF

# 1) run the attack (API keys come from $ROOT/.env via the walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --data "$GOALS_CSV" --sample-rows "$N_GOALS" --seed 0 \
  --compose-mode guided --num-strategies "$NUM_STRATEGIES" \
  --refine-rounds "$REFINE_ROUNDS" --optimus-backend llm \
  --composer api:deepseek/deepseek-v4-flash \
  --target "api:$VICTIM" --target-max-tokens 8192 \
  --optimus-judge api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash \
  --out "$RAW_OUT"

# 2) unified judge -> tmp then atomic mv to the final judged file
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_TMP"
mv "$JUDGED_TMP" "$JUDGED_OUT"
