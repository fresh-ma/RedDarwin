#!/usr/bin/env bash
# Adversarial Tales (2601.08837) attack on $VICTIM (default qwen/qwen3.7-flash),
# first $N_GOALS goals of $GOALS_FILE (default bench/AdvBench.csv),
# then unified judge. Only the judged file is kept in results/.
#
# Setting basis: the paper/skill ships a single configuration — two-arm design
# (baseline vs cyberpunk Proppian tale with fixed F14/F21 structural-analysis
# request), single-turn target, 3-judge 2-of-3 majority. The canonical preserved
# run (RESULT_2026-06-22.md) used the default token budgets (target 900 /
# transform 1100 / judge 400), so we keep them; there is no tokfix variant.
#
# Known risks / notes:
# - The skill's loader does NOT recognize AdvBench's `request` column (it wants
#   goal/prompt/behavior/...) and it seeded-shuffles before sampling, so we feed
#   a temp CSV holding exactly the first $N_GOALS goals under a `goal` column.
# - --target / --transform-model accept the `api:` prefix (stripped internally),
#   but --judges is passed to the API verbatim, so judges MUST be bare model ids.
# - Paper's judge ensemble is 3 DISTINCT open judges; benchmark policy forces
#   deepseek-v4-flash for the judging roles, so the panel is v4-flash x3 — the
#   2-of-3 shape is kept but ensemble diversity is lost (3x cost for near-identical
#   votes). unified_judge re-scores the tale arm with v4-flash anyway.
# - No separate attacker-LLM role exists; the transform model IS the attacker
#   (fixed meta-prompt, single step, no feedback loop), so it is NOT switched
#   with $VICTIM — only --target follows the victim.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Scenario-Nesting/2601.08837_AdversarialTales/adversarial-tales"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
# macOS mktemp replaces only trailing X's; a template like name_XXXXXX.csv ends
# up as name_XXXXXX.csv.<random> with a random extension the loaders reject, so
# use a temp dir and keep real .csv/.json names inside.
TMPD="$(mktemp -d -t adversarial-tales)"
GOALS_CSV="$TMPD/goals.csv"
RAW_OUT="$TMPD/raw.json"
trap 'rm -rf "$TMPD"' EXIT
JUDGED_OUT="$RESULTS/adversarial-tales_${VICTIM_SLUG}_propp-f14f21_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column (the skill
# shuffles before sampling, so feeding exactly $N_GOALS rows guarantees these
# goals regardless of seed)
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
"$PY" scripts/attack.py \
  --target "api:$VICTIM" \
  --transform-model api:deepseek/deepseek-v4-flash \
  --judges deepseek/deepseek-v4-flash,deepseek/deepseek-v4-flash,deepseek/deepseek-v4-flash \
  --dataset "$GOALS_CSV" --sample "$N_GOALS" --seed 0 \
  --target-max-tokens 900 --transform-max-tokens 1100 --judge-max-tokens 400 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
