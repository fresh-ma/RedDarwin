#!/usr/bin/env bash
# PAP (Persuasive Adversarial Prompt, 2401.06373) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv, first 5), then unified judge.
# Only the judged file is kept in results/.
#
# Setting basis: the canonical audited run
# (results/RESULT_2026-06-27.md + results/pap_v4flash_e2e_rerun.json) ran the
# default 3 techniques (Logical Appeal, Authority Endorsement, Evidence-based
# Persuasion) + direct baseline with --max-tokens 1536 (raised from 1024 — the
# token fix in the canonical rerun). 5 goals x 4 conditions = 20 cases.
#
# Known risks:
# - This skill calls OpenRouter directly and passes the model string verbatim
#   (scripts/models.py call_api), so the flags take BARE OpenRouter ids
#   (deepseek/deepseek-v4-flash), NOT the project api: prefix.
# - Attacker is v4-flash per project convention, but the canonical run used
#   attacker=gryphe/mythomax-l2-13b (a weakly-aligned paraphraser). v4-flash
#   may refuse or water down the persuasive paraphrase generation.
# - The canonical result on v4-flash was a faithful NEGATIVE (refusal_bypass
#   0.375, audited content_harmful 0.0): persuasion gets engagement but no
#   actionable harm, so a low/zero unified-judge ASR is expected, not a bug.
# - The skill's loader (scripts/cases.py) does not recognize AdvBench's
#   `request` column, and --sample uses a seeded random.sample (not "first N"),
#   so we feed a temp $N_GOALS-row CSV with a `goal` column (no --sample) to pin
#   the first $N_GOALS goals exactly.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Persuasion/2401.06373_PAP/pap"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
# NOTE: BSD mktemp -t appends the random suffix AFTER the whole template, so
# `mktemp -t name_XXXXXX.csv` yields `.../name_XXXXXX.csv.AbCdEf` whose
# extension is NOT .csv — the skill's loader (scripts/cases.py) rejects that
# with "unsupported dataset format". Create without the extension, then rename.
GOALS_CSV="$(mktemp -t pap_goals_XXXXXX)"
mv "$GOALS_CSV" "$GOALS_CSV.csv"
GOALS_CSV="$GOALS_CSV.csv"
RAW_OUT="$(mktemp -t pap_raw_XXXXXX)"
mv "$RAW_OUT" "$RAW_OUT.json"
RAW_OUT="$RAW_OUT.json"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/pap_${VICTIM_SLUG}_t3mt1536_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column (the skill's
# loader accepts goal/prompt/behavior/query/text; feeding exactly N_GOALS rows avoids
# the seeded random.sample in --sample and guarantees these N_GOALS)
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
with open(sys.argv[1], newline='', encoding='utf-8') as f:
    goals = [r['request'] for r in csv.DictReader(f)][:int(sys.argv[3])]
with open(sys.argv[2], 'w', newline='', encoding='utf-8') as g:
    w = csv.writer(g)
    w.writerow(['goal'])
    w.writerows([goal] for goal in goals)
EOF

# 1) run the attack (OPENROUTER_API_KEY comes from $ROOT/.env via the skill's
#    walk-up loader; bare OpenRouter model ids, no api: prefix — see header)
cd "$METHOD"
"$PY" scripts/attack.py \
  --attacker-model deepseek/deepseek-v4-flash \
  --target-model "$VICTIM" \
  --judge-model deepseek/deepseek-v4-flash \
  --dataset "$GOALS_CSV" \
  --techniques "Logical Appeal" "Authority Endorsement" "Evidence-based Persuasion" \
  --max-tokens 1536 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
