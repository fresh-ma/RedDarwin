#!/usr/bin/env bash
# emoji-jailbreak attack (2601.00936, emoji chaining/stuffing) on $VICTIM (default
# deepseek-v4-flash), first $N_GOALS goals from $GOALS_FILE (default AdvBench.csv
# first 5), then unified judge. Only the judged file is kept in results/.
#
# Setting: single strongest mode = chaining (paper Table-1 emoji substitution).
# Basis: the skill's only recorded run (results/emoji_deepseekchat_20x3_20260623_singlefolder.json,
# 20x3 modes) shows chaining best on every metric — keyword JSR 0.15 vs 0.10 (direct) / 0.05
# (stuffing), LLM refusal_bypass 0.45 vs 0.15 / 0.25. Paper JSR ≈ 10% overall: this is a
# deliberately WEAK attack, so low ASR is faithful, not a bug.
#
# Roles: victim --target-model is $VICTIM; judge --judge-model stays deepseek/deepseek-v4-flash.
# This skill takes bare OpenRouter ids (NO "api:" prefix) and hits OpenRouter directly.
# No attacker role: prompts are built by a fixed emoji-map generator, no helper LLM.
#
# Known risks / notes:
# - The skill's read_dataset() accepts goal/prompt/behavior/query/text columns only, NOT
#   AdvBench's "request"; and --sample uses a seeded shuffle, so "first N" can't be locked
#   that way. We therefore materialize a temp goal CSV (first $N_GOALS rows) below.
# - deepseek-v4-flash instead of the recorded deepseek-chat: paper targets were Ollama
#   7-9B models anyway (run is labeled model_substitution_run), so risk is limited to
#   ASR drift on an already weak attack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Single-turn/Encoding-Linguistic/2601.00936_EmojiJailbreak/emoji-jailbreak"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
# NOTE: BSD mktemp -t appends the random suffix AFTER the whole template, so
# "name_XXXXXX.csv" becomes "name_XXXXXX.csv.Ab12Cd34" and the skill's loader
# rejects the unknown suffix. Use a temp dir with properly-named files instead.
TMP_RUN="$(mktemp -d -t emoji_jailbreak)"
RAW_OUT="$TMP_RUN/raw.json"
GOALS_CSV="$TMP_RUN/goals.csv"
trap 'rm -rf "$TMP_RUN"' EXIT
JUDGED_OUT="$RESULTS/emoji-jailbreak_${VICTIM_SLUG}_chaining_${N_GOALS}x_${STAMP}.judged.json"

# 0) first $N_GOALS goals from $GOALS_FILE -> temp CSV with a 'goal' column the skill's
#    loader accepts
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
src, dst, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = list(csv.DictReader(open(src, newline="", encoding="utf-8")))
with open(dst, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["id", "goal", "category"])
    for i, r in enumerate(rows[:n]):
        w.writerow([i, r["request"], "advbench"])
EOF

# 1) run the attack: chaining only (strongest recorded mode); no --sample so the
#    $N_GOALS-row temp CSV is used as-is, in order (API key from $ROOT/.env via walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py \
  --target-model "$VICTIM" \
  --judge-model deepseek/deepseek-v4-flash \
  --dataset "$GOALS_CSV" \
  --modes chaining \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
