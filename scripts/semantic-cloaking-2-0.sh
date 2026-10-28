#!/usr/bin/env bash
# semantic-cloaking-2-0 — evolution of semantic-cloaking (S2C, arXiv 2603.16192).
# Mechanism changes vs parent:
#   1. Non-substitutable wrapper framing: the reframed scenario demands a direct full
#      answer to the embedded question itself and may not describe any benign
#      substitute task (fixes safe-redirect, ~60% of parent failures).
#   2. Intent-complete redaction: the extractor returns mechanics-bearing spans
#      (verbs/objects/materials/quantities), then up to 2 coverage self-check rounds
#      add spans until the plaintext residue carries no inferable harmful intent
#      (fixes decode-then-refuse, ~37% of parent failures; 100% on gpt-5.6-luna).
#   3. Reliable clue pool only: reversal+caesar / reversal+base64 / reversal+a1z26.
# Victim-call budget: 1 per goal (same as parent). Judge: unified judge downstream.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Proposal/semantic-cloaking-2-0"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t s2c2_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t s2c2_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/semantic-cloaking-2-0_${VICTIM_SLUG}_high_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals from $GOALS_FILE -> temp CSV with a `goal` column (skill's
# loader does not recognize the `request` column; it also shuffles before sampling,
# so feeding exactly $N_GOALS rows guarantees these rows regardless of seed)
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
cd "$METHOD/scripts"
"$PY" attack.py run \
  --reframer template \
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
