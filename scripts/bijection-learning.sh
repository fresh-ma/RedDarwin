#!/usr/bin/env bash
# Bijection Learning (arXiv:2410.01294) on $VICTIM (default deepseek-v4-flash),
# first $N_GOALS goals of $GOALS_FILE (default AdvBench.csv), then unified judge.
# Only the judged file is kept in results/.
#
# Attack: sample a random letter bijection, teach it in-context, send the
#   harmful query ENCODED + affirmative prefill, decode the reply and score it.
# Setting basis: single strongest config from the skill's canonical run
#   (SKILL.md headline + results/bijection_letter_v4flash_20x_mt16384_20260628.json):
#   letter bijection, fixed-size 18 (dispersion d=8), k_t=5 teaching shots,
#   max-message-length 240, prefill on, pass@4 trials, max-tokens 16384.
#   d=8 chosen over d=13: the skill's v4-flash d-sweep (RESULT_2026-06-26.md)
#   scored 0.167 at d=8 vs 0.083 at d=13, and the paper guides smaller models
#   to lower dispersion. max-tokens 16384 is the canonical "tokfix" budget —
#   v4-flash is a reasoning model and lower budgets (1536/8192, archived in
#   results/_process/) produced empty content after hidden reasoning spent it.
#   Only the `bijection` setting is run (the attack itself); `direct` is a
#   baseline arm and would dilute the judged ASR.
# Known risks:
#   - Bijection is CAPABILITY-GATED: the canonical v4-flash ASR is 0.000
#     (0/20, GLM reverse-audited as genuine). Expect a near-zero judged ASR —
#     that is the documented robustness boundary of a mid-size victim, not a
#     script failure (refusal_bypass was still 1.0).
#   - This skill has NO attacker LLM role by design: bijection maps are sampled
#     algorithmically (attacker_model=None in its output), so there is no
#     --attacker flag. Only --target and --judge exist; both take the
#     api:deepseek/deepseek-v4-flash id (attack.py strips the "api:" prefix
#     itself for OpenRouter).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Encoding-Linguistic/2410.01294_BijectionLearning/bijection-learning"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t bijection_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t bijection_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/bijection-learning_${VICTIM_SLUG}_d8p4mt16k_${N_GOALS}x_${STAMP}.judged.json"

# 0) first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column. The
#    skill's read_behaviors() accepts goal/Behavior/behavior (not `request`) but
#    reads rows IN ORDER with no shuffle, so $N_GOALS rows + --sample $N_GOALS
#    pins the first $N_GOALS.
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
with open(sys.argv[1], newline='', encoding='utf-8') as f:
    goals = [r['request'] for r in csv.DictReader(f)][:int(sys.argv[3])]
with open(sys.argv[2], 'w', newline='', encoding='utf-8') as g:
    w = csv.writer(g)
    w.writerow(['goal'])
    w.writerows([goal] for goal in goals)
EOF

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --settings bijection --bijection-type letter --fixed-size 18 \
  --num-teaching-shots 5 --max-message-length 240 --prefill \
  --trials 4 --sample "$N_GOALS" --workers 5 \
  --max-tokens 16384 \
  --dataset "$GOALS_CSV" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
