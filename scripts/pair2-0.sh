#!/usr/bin/env bash
# PAIR 2.0 (single-skill evolution of pair) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE, then unified judge.
# Only the judged file is kept in results/.
#
# Mechanism delta vs pair (paper-faithful base, streams x iterations budget
# identical at 2 x 3 = <=6 target calls per goal):
# - refusal-triggered re-seed: a stream whose last turn was a hard refusal
#   (judge 1 + refusal marker) is abandoned and re-initialized with the next
#   unused attacker framing instead of refining a dead branch;
# - cross-stream sharing: the case-wide best-scoring (prompt, response, score)
#   exemplar is injected into each stream's attacker feedback (2-island memetic
#   coupling);
# - attacker fallback: api:deepseek/deepseek-v4-flash is retried when the primary attacker
#   never yields parseable JSON (recovers skipped_attacker_failed turns).
#
# Frozen variant defaults below (see EXPERIMENTS.md); env overrides exist only
# for probe-time ablations.
# Frozen variant defaults (selected by mean probe ASR across the panel, seeds
# 43-47; see EXPERIMENTS.md): 6 streams x 1 iteration, no answer-prefill.
# Env overrides exist only for probe-time ablations.
RESEED_ON_REFUSAL="${RESEED_ON_REFUSAL:-on}"
SHARE_BEST="${SHARE_BEST:-on}"
ATTACKER_FALLBACK="${ATTACKER_FALLBACK:-api:deepseek/deepseek-v4-flash}"
STREAMS="${STREAMS:-6}"
ITERATIONS="${ITERATIONS:-1}"
ANSWER_PREFILL="${ANSWER_PREFILL:-off}"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/pair2-0"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t pair2_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t pair2_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/pair2_${VICTIM_SLUG}_s${STREAMS}i${ITERATIONS}_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with goal,target columns
# (same normalization as the parent wrapper: the skill's load_cases shuffles
# before sampling, so feeding exactly N_GOALS rows guarantees the first N_GOALS)
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
with open(sys.argv[1], newline='', encoding='utf-8') as f:
    rows = [(r['request'], r['target']) for r in csv.DictReader(f)][:int(sys.argv[3])]
with open(sys.argv[2], 'w', newline='', encoding='utf-8') as g:
    w = csv.writer(g)
    w.writerow(['goal', 'target'])
    w.writerows(rows)
EOF

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --data "$GOALS_CSV" --sample-rows "$N_GOALS" --seed 7 \
  --attacker api:deepseek/deepseek-v4-flash \
  --attacker-fallback "$ATTACKER_FALLBACK" \
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --streams "$STREAMS" --iterations "$ITERATIONS" --strategies roleplay,logical,authority \
  --reseed-on-refusal "$RESEED_ON_REFUSAL" --share-best "$SHARE_BEST" \
  --answer-prefill "$ANSWER_PREFILL" \
  --target-max-tokens 2048 --judge-max-tokens 3000 --attack-max-tokens 1500 \
  --case-workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
