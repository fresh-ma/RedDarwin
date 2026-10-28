#!/usr/bin/env bash
# semantic-cloaking (S2C, Structured Semantic Cloaking, arXiv 2603.16192) attack on
# $VICTIM (default deepseek-v4-flash), first $N_GOALS goals from $GOALS_FILE
# (default AdvBench.csv first 5), then unified judge.
# Only the judged file is kept in results/.
#
# Setting: canonical config from the skill's RESULT_2026-07-17.md — default cascade
# method pool + difficulty=high (content_harmful 0.45 vs 0.25 at medium on JBB-20;
# difficulty=high is the stronger of the two canonical runs), seed 11,
# target-max-tokens 4096, judge-max-tokens 128.
#
# Known risks:
# - Model substitution (documented in SKILL.md): paper uses Gemma-2-9B-it reframer,
#   GPT-4.1-mini extractor, HarmBench Llama-2-13B classifier judge; here reframer/
#   extractor/judge stay api:deepseek/deepseek-v4-flash and target is api:$VICTIM,
#   so absolute ASR is not comparable to the paper's numbers.
# - Dataset substitution: canonical runs used JBB-Behaviors; here first $N_GOALS
#   rows of $GOALS_FILE (default AdvBench first 5).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Single-turn/Encoding-Linguistic/2603.16192_SemanticCloaking/semantic-cloaking"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t s2c_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t s2c_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/semantic-cloaking_${VICTIM_SLUG}_high_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals from $GOALS_FILE -> temp CSV with a `goal` column (skill's loader
# does not recognize the `request` column; it also shuffles before sampling, so feeding
# exactly $N_GOALS rows guarantees these rows regardless of seed)
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
  --reframer api:deepseek/deepseek-v4-flash \
  --extractor api:deepseek/deepseek-v4-flash \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --data "$GOALS_CSV" --sample-rows "$N_GOALS" \
  --difficulty high --seed 11 --case-workers 5 \
  --target-max-tokens 4096 --judge-max-tokens 128 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
