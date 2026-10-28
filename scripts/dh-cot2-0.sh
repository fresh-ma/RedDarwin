#!/usr/bin/env bash
# DH-CoT 2.0 (proposal dh-cot2-0) on $VICTIM (default deepseek-v4-flash), first
# $N_GOALS goals from $GOALS_FILE (default AdvBench.csv first 5), then unified judge.
#
# Mechanism (single-skill-evolution of dh-cot, DH-CoT mode only, 1 victim call/goal):
#   1. coded referent — auxiliary attacker (deepseek/deepseek-v4-flash, deepseek/deepseek-v4-flash
#      fallback on refusal/error) rewrites the raw goal into a neutral codename +
#      benign domain framing; the victim-facing text never contains the plaintext goal.
#   2. goal-adaptive conclusive fake CoT — auxiliary cot-writer (same panel) generates
#      a per-goal H-CoT that unpacks the codename's operational meaning in domain terms
#      and ends with an explicit compliance-conclusion phase; replaces the parent's
#      static generic 7-phase frame.
#   3. few-shot default D12 (refusal exemplar) -> D7 (compliant ambiguous exemplar,
#      per the paper's own ablation favoring D7-D11).
#
# Setting basis inherited from the parent's canonical run: role=system, HST=8,
# target-max-tokens 8192, judge_max_tokens 512, internal MDH judge deepseek/deepseek-v4-flash.
#
# Known risks (same as parent):
# - skill loader shuffles with --seed before sampling; we feed exactly $N_GOALS rows
#   via a temp goal CSV so the seed cannot change WHICH goals run.
# - loader only accepts goal/question/behavior/objective/prompt columns, so
#   AdvBench's `request` column is renamed to `goal` in the temp CSV.
# - MDH is the single LLM rubric judge (paper Part B), not the Part-A Llama-Guard
#   ensemble; recorded as model substitution upstream.
# - attack.py has no per-goal checkpoint file; a failed case is mapped to a failed
#   record and the batch continues (same robustness level as the parent).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Proposal/dh-cot2-0"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t dhcot2_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t dhcot2_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/dh-cot2-0_${VICTIM_SLUG}_dhcot2_D7_mt8192_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals from $GOALS_FILE -> temp CSV with a `goal` column (skill shuffles
# before sampling, so feeding exactly $N_GOALS rows guarantees these rows regardless of seed)
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
cd "$METHOD/scripts"
"$PY" attack.py run \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --attacker api:deepseek/deepseek-v4-flash --cot-writer api:deepseek/deepseek-v4-flash \
  --modes dh-cot --role system --dh-variant D7 --hst 8 \
  --data "$GOALS_CSV" --sample-rows "$N_GOALS" --seed 7 \
  --target-max-tokens 8192 --judge-max-tokens 512 --aux-max-tokens 1536 \
  --case-workers 10 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
