#!/usr/bin/env bash
# Crescendo 2.0 (proposal crescendo-2-0, PyRIT Crescendo evolution) on $VICTIM
# (default deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv), then the unified judge. Sequential (a shard is usually 1
# goal). Resume-safe: the raw output name is deterministic per shard (victim
# slug + short sha of the extracted goals), attack.py skips goals already
# completed in it, and a judged file covering all goals short-circuits the run.
# Only the judged file and the raw checkpoint are kept in results/.
#
# Attacker uses qwen3.7-flash with qwen3.5-9b fallback on refusal/error.
# Settings follow the parent's canonical audited run: max_turns=6,
# max_backtracks=2, target/attacker_max_tokens=2048, judge_max_tokens=1024.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
METHOD="$ROOT/XSkillLib/Proposal/crescendo-2-0"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
VICTIM_SLUG="${VICTIM##*/}"
mkdir -p "$RESULTS"

GOALS_CSV="$(mktemp -t crescendo2_goals_XXXXXX.csv)"
JUDGED_TMP="$(mktemp -t crescendo2_judged_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$JUDGED_TMP"' EXIT

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

# deterministic per-shard names: re-invocation of the same shard resumes/skips
SHARD_ID="$(shasum -a 256 "$GOALS_CSV" | cut -c1-8)"
RAW_OUT="$RESULTS/crescendo-2-0_${VICTIM_SLUG}_${SHARD_ID}.raw.json"
JUDGED_OUT="$RESULTS/crescendo-2-0_${VICTIM_SLUG}_${SHARD_ID}.judged.json"

# resume-safe: skip the attack entirely when the judged file already covers all goals
if [ -f "$JUDGED_OUT" ] && "$PY" - "$JUDGED_OUT" "$N_GOALS" <<'EOF'
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as f:
        data = json.load(f)
except Exception:
    sys.exit(1)
results = data.get('results') or data.get('records') or []
complete = len(results) >= int(sys.argv[2]) and all(
    isinstance(row.get('unified_judge'), dict)
    and row['unified_judge'].get('score') is not None
    for row in results
)
sys.exit(0 if complete else 1)
EOF
then
  echo "resume: $JUDGED_OUT already covers $N_GOALS goals; skipping" >&2
  exit 0
fi

# 1) run the attack (API keys come from the walk-up .env loader; attack.py
#    writes $RAW_OUT incrementally and skips goals it already completed)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --goals "$GOALS_CSV" --sample-rows "$N_GOALS" --seed 20260626 \
  --target "api:$VICTIM" \
  --attacker api:deepseek/deepseek-v4-flash \
  --attacker-fallback api:deepseek/deepseek-v4-flash \
  --judge-model api:deepseek/deepseek-v4-flash \
  --settings-max-turns 6 --max-backtracks 2 \
  --target-max-tokens 2048 --attacker-max-tokens 2048 --judge-max-tokens 1024 \
  --out "$RAW_OUT"

# 2) unified judge -> atomic single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_TMP"
mv "$JUDGED_TMP" "$JUDGED_OUT"
