#!/usr/bin/env bash
# breakme2-0 (evolved LATS: goal-conditioned seed pool, index-only inspection,
# refusal-aware pruning) attack on $VICTIM, first $N_GOALS goals of $GOALS_FILE,
# parent hyper-params (N=30 k=4 R=2 D=4, max-queries 40), then unified judge.
# Only the judged file is kept in results/.
set -euo pipefail

# huggingface.co is unreachable from this network; use the mirror so the
# paraphrase encoder (st:paraphrase-MiniLM-L6-v2) can download. Without it the
# skill retries then silently degrades to the lexical fallback.
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
# models are already in the local HF cache; skip hub HEAD checks (they hang
# for minutes on retries when the network is flaky) and load from cache.
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
SKILL="$ROOT/XSkillLib/Proposal/breakme2-0/skill"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t breakme2_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t breakme2_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/breakme2-0_${VICTIM_SLUG}_N30k4d4_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column (skill
# shuffles before sampling, so feeding exactly N_GOALS rows guarantees these
# regardless of seed)
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
with open(sys.argv[1], newline='', encoding='utf-8') as f:
    goals = [r['request'] for r in csv.DictReader(f)][:int(sys.argv[3])]
with open(sys.argv[2], 'w', newline='', encoding='utf-8') as g:
    w = csv.writer(g)
    w.writerow(['goal'])
    w.writerows([goal] for goal in goals)
EOF

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$SKILL"
"$PY" attack.py run \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --json-fixer api:deepseek/deepseek-v4-flash \
  --data "$GOALS_CSV" --sample-rows "$N_GOALS" \
  --n 30 --k 4 --r-retry 2 --d-max 4 --tau-word 0.8 --max-queries 40 \
  --seed 7 --case-workers 5 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
