#!/usr/bin/env bash
# Virtual Context (arXiv 2406.19845) attack on $VICTIM (default
# deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# AdvBench.csv), then unified judge.
#
# Setting basis: the canonical run
#   results/virtual_context_api-deepseek-deepseek-v4-flash_plain_sep_n20_20260722-041716.json
# (audited in the skill's RESULT_2026-07-22.md) uses template=plain,
# separator=sep, confirmation-style=dataset, target-max-tokens=1024,
# reasoning OFF. That is the SKILL.md-documented, tokfix/canonical config, so
# we reuse it unchanged. Note the paper has a single standalone Direct+VC
# configuration; no stronger variant exists in this skill's results.
#
# Roles: this attack is a fixed-payload single-turn prompt injection — there is
# NO attacker/assistant LLM by design; only --target (victim) and --judge are
# configurable, both pinned to api:deepseek/deepseek-v4-flash.
#
# Known risks (from the skill's RESULT_2026-07-22.md / CONSOLIDATE_BLOCKER.md):
#   - OpenRouter chat-completions delivers <SEP> as literal user text, not a
#     real tokenizer-level control token, so the Virtual Context primitive may
#     not fully fire via API (era-gap / faithful-negative expected on V4 Flash).
#   - Historical runs against deepseek-v4-flash scored 0/20; treat the output
#     as a prompt-render observation, not strong attack evidence.
#   - The loader's --sample uses a seeded shuffle, so to guarantee the FIRST
#     $N_GOALS goals of $GOALS_FILE we materialize them into a temp CSV and pass
#     it via --dataset (loader accepts the `request` column).
#
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Response-Prefill/2406.19845_VirtualContext/virtual-context"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t virtual_context_raw_XXXXXX.json)"
GOALS_CSV="$(mktemp -t virtual_context_goals_XXXXXX.csv)"
trap 'rm -f "$RAW_OUT" "$GOALS_CSV"' EXIT
JUDGED_OUT="$RESULTS/virtual-context_${VICTIM_SLUG}_plain_sep_${N_GOALS}x_${STAMP}.judged.json"

# 0) materialize the first $N_GOALS goals of $GOALS_FILE (columns request,target;
#    the skill's loader reads `request` as goal and `target` as the affirmative suffix)
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'PYEOF'
import csv, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src, newline="", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
with open(dst, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows[:int(sys.argv[3])])
PYEOF

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --dataset "$GOALS_CSV" \
  --sample "$N_GOALS" \
  --template plain --separator sep --confirmation-style dataset \
  --target-max-tokens 1024 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
