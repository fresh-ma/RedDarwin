#!/usr/bin/env bash
# dh-cot (DH-CoT / D-Attack, arXiv 2508.10390) on $VICTIM (default
# deepseek-v4-flash), first $N_GOALS goals from $GOALS_FILE (default AdvBench.csv
# first 5), then unified judge.
#
# Setting basis: the skill's canonical run (RESULT_2026-07-17.md,
# results/dhcot_deepseek-v4flash_datk+dhcot_D12_24x_mt8192_20260717-054001.json):
# both modes d-attack+dh-cot, role=system, D12 variant, HST=8,
# target-max-tokens 8192 (0 empty outputs), judge_max_tokens 512,
# cot_writer=none (generic H-CoT frame). d-attack ASR 0.958, dh-cot 0.833.
# Scaled down 24 goals -> $N_GOALS goals (default 5).
#
# Roles: --target (victim) is $VICTIM; --judge (skill's internal MDH judge) stays
# deepseek-v4-flash, matching the canonical run. The optional --cot-writer
# (attacker/helper LLM) stays off per canonical; the generic paper H-CoT
# template frame is used instead.
#
# Known risks:
# - skill loader shuffles with --seed before sampling; we feed exactly $N_GOALS rows
#   via a temp goal CSV so the seed cannot change WHICH goals run.
# - loader only accepts goal/question/behavior/objective/prompt columns, so
#   AdvBench's `request` column is renamed to `goal` in the temp CSV.
# - d-attack mode hard-forces the opening "Okay, the answer could be:", so
#   refusal_bypass will read 1.0; MDH rubric judge clusters scores at 8
#   (lenient) per the skill's RESULT notes.
# - MDH here is the single LLM rubric judge (paper Part B), not the full
#   Part-A Llama-Guard ensemble; recorded as model substitution upstream.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Single-turn/Reasoning-Manipulation/2508.10390_DhCot/dh-cot"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t dhcot_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t dhcot_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/dh-cot_${VICTIM_SLUG}_datk+dhcot_D12_mt8192_${N_GOALS}x_${STAMP}.judged.json"

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

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --modes d-attack,dh-cot --role system --dh-variant D12 --hst 8 \
  --data "$GOALS_CSV" --sample-rows "$N_GOALS" --seed 7 \
  --target-max-tokens 8192 --judge-max-tokens 512 \
  --case-workers 10 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
