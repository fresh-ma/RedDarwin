#!/usr/bin/env bash
# LinguaBreak (multi-skill-combination of breakme2-0 + translation-jailbreak2-0)
# on $VICTIM, first $N_GOALS goals of $GOALS_FILE, frozen defaults
# (N=30 k=4 R=2 D=4, victim-call budget 40/goal — every victim call counts),
# then the unified judge. Only the judged file is kept in results/.
#
# Fusion: parent A's guardrail-dataset search over a shared exemplar-pool IR;
# parent B's LRL fragment-relay as refusal-routed repair operators (seed repair
# + stalled-pair re-serialization). Auxiliary LLMs (AGENTS.md fixed):
# deepseek/deepseek-v4-flash primary, deepseek/deepseek-v4-flash fallback — never the victim.
#
#   - the raw output path is stable per (victim, N_GOALS, results dir) so a
#     retried wrapper resumes the runner's per-case atomic checkpoint instead
#     of re-paying completed cases.
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
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
SKILL="$ROOT/XSkillLib/Proposal/linguabreak/skill"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, api: prefix added below
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
GOAL_WORKERS="${GOAL_WORKERS:-5}"
ATTACK_RESULTS_DIR="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
xsf_parse_args "$@"; rc=$?; ((rc == 0 && ${XSF_HELP:-0} == 1)) && exit 0; ((rc == 0)) || exit "$rc"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="$ATTACK_RESULTS_DIR"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t linguabreak_goals_XXXXXX.csv)"
trap 'rm -f "$GOALS_CSV"' EXIT
RAW_OUT="$RESULTS/linguabreak_${VICTIM_SLUG}_N30k4d4_${N_GOALS}x_raw.json"
JUDGED_OUT="$RESULTS/linguabreak_${VICTIM_SLUG}_N30k4d4_${N_GOALS}x_${STAMP}.judged.json"

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
  --seed 7 --case-workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
