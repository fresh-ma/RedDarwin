#!/usr/bin/env bash
# CipherChat (2308.06463) on $VICTIM (default deepseek-v4-flash), first $N_GOALS
# goals from $GOALS_FILE (default AdvBench.csv first 5),
# strongest single setting (SelfCipher, Crimes_And_Illegal_Activities demos,
# max-tokens 8192 = canonical tokfix run), then unified judge.
# Setting basis: results/RESULT_2026-06-26.md — SelfCipher is the strongest
# variant (ZH-Crimes 0.733; EN-Crimes best among EN configs); canonical
# v4-flash runs used --max-tokens 8192 (cc_v4flash_*_mt8192_*.json).
# Roles: victim = --target is $VICTIM; judge = --judge stays v4-flash. No attacker
# role: the attack is a fixed official prompt pack (cipher role + enciphered demos),
# no auxiliary LLM involved.
# Known risks: (1) the skill's loader only reads a JSON goal list, so $GOALS_FILE
#   is converted to a temp JSON below (first $N_GOALS rows, order preserved, demos pinned
#   to Crimes_And_Illegal_Activities to match the strongest config);
# (2) the skill's built-in dual-metric judge is known to over-count ~21% on
#   ciphered EN outputs (GLM audit) — trust the unified_judge verdicts instead.
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-10}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Single-turn/Encoding-Linguistic/2308.06463_CipherChat/cipherchat"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t cipherchat_raw_XXXXXX.json)"
GOALS_JSON="$(mktemp -t cipherchat_goals_XXXXXX.json)"
trap 'rm -f "$RAW_OUT" "$GOALS_JSON"' EXIT
JUDGED_OUT="$RESULTS/cipherchat_${VICTIM_SLUG}_selfcipher_mt8192_${N_GOALS}x_${STAMP}.judged.json"

# 0) first $N_GOALS goals from $GOALS_FILE -> temp JSON the skill's loader accepts
#    (loader keys: goal/id/lang/demo_domain; demo_domain pinned to Crimes
#    so the official Crimes unsafe demos are used, matching the canonical run)
"$PY" - "$GOALS_FILE" "$GOALS_JSON" "$N_GOALS" <<'PYEOF'
import csv, json, sys
src, dst, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = []
with open(src, newline="", encoding="utf-8") as f:
    for i, row in enumerate(csv.DictReader(f)):
        if i >= n:
            break
        rows.append({
            "id": i + 1,
            "goal": row["request"].strip(),
            "category": "Crimes_And_Illegal_Activities",
            "demo_domain": "Crimes_And_Illegal_Activities",
            "lang": "en",
        })
if len(rows) != n:
    raise SystemExit(f"expected {n} goals from {src}, got {len(rows)}")
with open(dst, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=1)
PYEOF

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --ciphers selfcipher \
  --dataset "$GOALS_JSON" \
  --limit-rows "$N_GOALS" \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --max-tokens 8192 --temperature 0 \
  --concurrency "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
