#!/usr/bin/env bash
# ART / OPTIMUS compositional jailbreak (2605.09225) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv), then unified judge.
# Only the judged file is kept in results/.
#
# Setting basis: the skill's canonical audited run
# (RESULT_20260720.md + results/art_deepseek-deepseek-v4-flash_randoms3_20x_20260720-001410.json)
# is the paper's single configuration: num_strategies=3, strategy_mode=random,
# optimus_backend=llm (Listing-3 Likert rubric, fully black-box), seed=0,
# target = api:$VICTIM; composer = optimus_judge = judge = api:deepseek/deepseek-v4-flash
# (audited content_harmful 6/20 = 0.30, refusal_bypass 0.25).
#
# Known risks:
# - No separate attacker role: the auxiliary LLM is the --composer (Compose(q,s)
#   generator); --target is the victim (the only role switched by $VICTIM). The
#   skill additionally has two scoring roles (--optimus-judge, --judge); these
#   three stay on v4-flash per convention.
# - A hosted chat model as composer may refuse to compose harmful jailbreak
#   prompts (compose_status != ok yields an empty jailbreak prompt and a failed
#   case); canonical evidence shows v4-flash works.
# - optimus_backend=local (SBERT+DeBERTa, GPU/HF) exists but the canonical run
#   used the llm backend; we stay with canonical.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Persona-Roleplay/2605.09225_ArtOfJailbreak/art-jailbreak"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t art_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t art_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/art-jailbreak_${VICTIM_SLUG}_randoms3_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column (the
# skill's load_cases does not accept the `request` column and shuffles with the
# seed before sampling, so feeding exactly $N_GOALS rows guarantees the first
# $N_GOALS goals regardless of seed)
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
  --data "$GOALS_CSV" --sample-rows "$N_GOALS" --seed 0 \
  --num-strategies 3 --strategy-mode random --optimus-backend llm \
  --composer api:deepseek/deepseek-v4-flash \
  --target "api:$VICTIM" \
  --optimus-judge api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
