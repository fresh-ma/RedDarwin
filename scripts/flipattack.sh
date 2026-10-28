#!/usr/bin/env bash
# FlipAttack (2410.02832) on $VICTIM (default deepseek-v4-flash), first $N_GOALS
# goals from $GOALS_FILE (default AdvBench.csv first 5),
# strongest single setting, then unified judge.
#
# Setting basis: canonical run is FCS + CoT + LangGPT (paper's strongest documented
# variant; results/RESULT_2026-06-27.md, audited ASR-GPT 0.54). max-tokens 8192 is
# the 2026-06-28 remediation: v4-flash is a reasoning model and at 1536 tokens it
# spent the budget on hidden reasoning, returning empty content; the mt8192 rerun
# had 50/50 ok, 0 empties (asr_gpt 0.52, consistent with 0.54).
#
# Known risks / notes:
# - No attacker/helper LLM by design: FlipAttack is a deterministic string
#   transform, so only victim + judge flags exist.
# - The skill's built-in ASR-GPT judge flag is --judge-model with a BARE model id
#   (no api: prefix; it shares the target's OpenRouter gateway). It runs the
#   paper's PAIR 1-10 judge inline, so judge calls happen twice (skill + unified
#   judge). Keeping it on preserves the skill's canonical dual-metric raw output.
# - --sample N does a seeded shuffle and cannot guarantee "first N", so this
#   script builds a temp CSV from the first $N_GOALS $GOALS_FILE request rows and feeds
#   it via --goals (the loader accepts goal/Goal/Behavior/question/request).
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Single-turn/Encoding-Linguistic/2410.02832_FlipAttack/flipattack"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t flipattack_raw_XXXXXX.json)"
GOALS_CSV="$(mktemp -t flipattack_goals_XXXXXX.csv)"
trap 'rm -f "$RAW_OUT" "$GOALS_CSV"' EXIT
JUDGED_OUT="$RESULTS/flipattack_${VICTIM_SLUG}_fcs_mt8192_${N_GOALS}x_${STAMP}.judged.json"

# 0) temp goals CSV: first $N_GOALS goals from $GOALS_FILE (request column)
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
src, dst, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
with open(src, newline="", encoding="utf-8", errors="replace") as f, \
     open(dst, "w", newline="", encoding="utf-8") as out:
    w = csv.writer(out)
    w.writerow(["goal"])
    for i, row in enumerate(csv.DictReader(f)):
        if i >= n:
            break
        w.writerow([row["request"]])
EOF

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --goals "$GOALS_CSV" \
  --mode FCS --cot --langgpt \
  --max-tokens 8192 \
  --target "api:$VICTIM" \
  --judge-model deepseek/deepseek-v4-flash \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
