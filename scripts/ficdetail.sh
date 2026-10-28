#!/usr/bin/env bash
# FicDetail (2505.17650) attack on $VICTIM (default deepseek-v4-flash), first
# $N_GOALS goals of $GOALS_FILE (default AdvBench.csv),
# then unified judge. Only the judged file is kept in results/.
#
# Attack: fixed 3-turn fictional-detail jailbreak (fiction -> "technical details"
#   -> "specific experimental procedure"), final reply scored on the paper's
#   GPT-4 1..5 AHS/ASR rubric.
# Setting basis: the attack is a SINGLE fixed configuration by design (verbatim
#   3-turn ladder, Figure 2 of the paper) — there is no stronger/weaker variant.
#   We keep the skill's documented success-mode defaults: --target-max-tokens 2048
#   (SKILL.md: "long detailed answers are the success mode"), temperature 0.0.
#   Historical run results/deakin_20260720-085645.json used the same defaults.
# Known risks:
#   - FicDetail has NO attacker LLM role by design (payload_contract=direct, fixed
#     turns); only --target and --judge-model exist, so there is no --attacker flag
#     to set — nothing to override.
#   - The skill's loader shuffles before slicing (--sample-rows), so the goals
#     file cannot be passed directly to guarantee the FIRST $N_GOALS goals; this
#     script builds a temp CSV with exactly the first $N_GOALS `request` rows (no
#     skill patch needed; shuffling N rows and taking N keeps all of them).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Multi-turn/Crescendo/2505.17650_Ficdetail/ficdetail"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t ficdetail_raw_XXXXXX.json)"
GOALS_CSV="$(mktemp -t ficdetail_goals_XXXXXX.csv)"
trap 'rm -f "$RAW_OUT" "$GOALS_CSV"' EXIT
JUDGED_OUT="$RESULTS/ficdetail_${VICTIM_SLUG}_3turn_tk2048_${N_GOALS}x_${STAMP}.judged.json"

# 0) pin the FIRST $N_GOALS goals of $GOALS_FILE (column: request) into a temp CSV
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
with open(sys.argv[1], newline="", encoding="utf-8") as src, \
     open(sys.argv[2], "w", newline="", encoding="utf-8") as dst:
    reader, writer = csv.DictReader(src), csv.writer(dst)
    writer.writerow(["goal"])
    for i, row in enumerate(reader):
        if i >= int(sys.argv[3]):
            break
        writer.writerow([row["request"]])
EOF

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --goals "$GOALS_CSV" \
  --target "api:$VICTIM" \
  --judge-model api:deepseek/deepseek-v4-flash \
  --sample-rows "$N_GOALS" --seed 20260720 \
  --target-max-tokens 2048 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
