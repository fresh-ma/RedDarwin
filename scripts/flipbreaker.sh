#!/usr/bin/env bash
# FlipBreaker (proposal flipbreaker, fragment-keyed decoder chain;
# multi-skill-combination of actorbreaker-2-0 + flipattack-2-0) on $VICTIM
# (default deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/advbench_50.csv), then the unified judge. Sequential shards
# (usually 1 goal). Resume-safe: raw/judged names are deterministic per shard
# (victim slug + short sha of the shard goals), the attack itself checkpoints
# atomically per goal and only status=="ok" cells count as done, and a judged
# file covering all goals short-circuits the run. Only the judged file is kept
# in results/.
#
# Frozen settings: actors=1 (one fragment-keyed chain per goal), register-locked
# dynamic-modify retry (max 1 per turn), hard victim-call budget 10 per goal
# (proposal.json evaluation_budget), target_max_tokens=8192 (reasoning victims
# burn hidden tokens), victim temperature 0. Aux LLM for every attacker role is
# pinned to api:deepseek/deepseek-v4-flash; OpenRouter provider failover for it
# (GMICloud/DigitalOcean/Sail/DeepInfra) is injected by
# runtime_hooks/sitecustomize.py via PYTHONPATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
METHOD="$ROOT/XSkillLib/Proposal/flipbreaker"
PY="$ROOT/.venv/bin/python"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/advbench_50.csv}"
N_GOALS="${N_GOALS:-5}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
VICTIM_SLUG="${VICTIM##*/}"
mkdir -p "$RESULTS"

GOALS_CSV="$(mktemp -t flipbreaker_goals_XXXXXX.csv)"
JUDGED_TMP="$(mktemp -t flipbreaker_judged_XXXXXX.json)"
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
RAW_OUT="$RESULTS/flipbreaker_${VICTIM_SLUG}_${SHARD_ID}.raw.json"
JUDGED_OUT="$RESULTS/flipbreaker_${VICTIM_SLUG}_${SHARD_ID}.judged.json"

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

# 1) run the attack (API keys come from the walk-up .env loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --target "api:$VICTIM" \
  --attacker api:deepseek/deepseek-v4-flash \
  --goals "$GOALS_CSV" \
  --actors 1 --max-target-calls 10 --target-max-tokens 8192 \
  --workers 5 \
  --out "$RAW_OUT"

# 2) unified judge -> atomic single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_TMP"
mv "$JUDGED_TMP" "$JUDGED_OUT"
