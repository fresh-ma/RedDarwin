#!/usr/bin/env bash
# Crescendo (PyRIT-faithful port, 2404.01833) on $VICTIM (default
# deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# AdvBench.csv), then unified judge.
# Only the judged file is kept in results/.
#
# Setting basis: the skill's canonical audited run
# (results/RESULT_2026-06-26.md + results/crescendo_advbench50_v4flash_tokfix_20260626.json)
# ran max_turns in {4,6} with the "tokfix" budgets; per-setting ASR was 5/6 at
# max_turns=4 vs 6/6 at max_turns=6, so the single strongest setting is
# max_turns=6 + max_backtracks=2 + target/attacker_max_tokens=2048 +
# judge_max_tokens=1024 (the token fix is essential: the old 700/500 budgets
# truncated harmful payloads and produced a fake 0.50 ASR).
#
# Known risks:
# - attacker is v4-flash per project convention, but the skill defaults the
#   attacker to a local ollama:uncensored model (a hosted chat model may refuse
#   the red-team role or emit non-JSON, ending a case early via
#   adversarial_parse_failed). Canonical evidence shows v4-flash works (11/12),
#   but per-case parse failures remain possible.
# - judge flag is --judge-model (not --judge); all three roles are the same
#   self-judge v4-flash, as in the canonical run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Multi-turn/Crescendo/2404.01833_Crescendo/crescendo"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t crescendo_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t crescendo_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/crescendo_${VICTIM_SLUG}_mt6_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column (the
# skill's choose() shuffles before sampling, so feeding exactly $N_GOALS rows
# guarantees the first $N_GOALS regardless of seed)
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
  --goals "$GOALS_CSV" --sample-rows "$N_GOALS" --seed 20260626 \
  --target "api:$VICTIM" \
  --attacker api:deepseek/deepseek-v4-flash \
  --judge-model api:deepseek/deepseek-v4-flash \
  --settings-max-turns 6 --max-backtracks 2 \
  --target-max-tokens 2048 --attacker-max-tokens 2048 --judge-max-tokens 1024 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
