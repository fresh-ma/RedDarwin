#!/usr/bin/env bash
# CIA-Context 2.0 (proposal cia-context2-0, adaptive CIA ladder) on $VICTIM
# (default deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/advbench_50.csv), then the unified judge. Runs goals SEQUENTIALLY (one
# process; $GOAL_WORKERS is accepted for interface compatibility but the
# adaptive ladder keeps a per-goal transcript, so a shard is usually 1 goal).
# Resume-safe: the raw output name is deterministic per shard (victim slug +
# short sha of the extracted goals), attack.py skips goals already completed in
# it, and a judged file covering all goals short-circuits the run. Only the
# judged file and the raw checkpoint are kept in results/.
#
# Budget/settings follow the proposal: max-turns (victim-call budget) = 10 (the
# parent's observed max), target_max_tokens=4096 (mechanism v2: the reasoning
# victim truncated the final deliverable at 2048), attacker_max_tokens=2048,
# judge_max_tokens=1024.
# Model ids are BARE OpenRouter ids (no api: prefix) for this skill family.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
METHOD="$ROOT/XSkillLib/Proposal/cia-context2-0"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
GOAL_WORKERS="${GOAL_WORKERS:-1}"                     # documented: runs sequentially
VICTIM_SLUG="${VICTIM##*/}"
mkdir -p "$RESULTS"

GOALS_CSV="$(mktemp -t cia2_goals_XXXXXX.csv)"
JUDGED_TMP="$(mktemp -t cia2_judged_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$JUDGED_TMP"' EXIT

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column
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
RAW_OUT="$RESULTS/cia-context2-0_${VICTIM_SLUG}_${SHARD_ID}.raw.json"
JUDGED_OUT="$RESULTS/cia-context2-0_${VICTIM_SLUG}_${SHARD_ID}.judged.json"

# resume-safe: skip the attack entirely when the judged file already covers all goals
if [ -f "$JUDGED_OUT" ] && "$PY" - "$JUDGED_OUT" "$N_GOALS" <<'EOF'
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as f:
        data = json.load(f)
except Exception:
    sys.exit(1)
results = data.get('results') or data.get('records') or []
sys.exit(0 if len(results) >= int(sys.argv[2]) else 1)
EOF
then
  echo "resume: $JUDGED_OUT already covers $N_GOALS goals; skipping" >&2
  exit 0
fi

# 1) run the attack (API keys come from the walk-up .env loader; attack.py
#    writes $RAW_OUT incrementally and skips goals it already completed)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --goals "$GOALS_CSV" --sample-rows "$N_GOALS" \
  --target "$VICTIM" \
  --attacker deepseek/deepseek-v4-flash \
  --judge-model deepseek/deepseek-v4-flash \
  --max-turns 10 \
  --target-max-tokens 4096 --attacker-max-tokens 2048 --judge-max-tokens 1024 \
  --out "$RAW_OUT"

# 2) unified judge -> atomic single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_TMP"
mv "$JUDGED_TMP" "$JUDGED_OUT"
