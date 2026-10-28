#!/usr/bin/env bash
# h4rm3l (2408.04811, composable jailbreak DSL) on $VICTIM (default
# deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# AdvBench.csv), then unified judge.
#
# Setting: single strongest program `synth_chardropout_aim` =
# CharDropout(seed=42, p=0.05).then(AIMDecorator()).then(RefusalSuppressionDecorator())
# — the top program of the canonical bandit-synthesis run (skill results/
# RESULT_2026-06-26.md + synth_v4flash_canonical_20260626.json): raw ASR(B) 1.00,
# GLM-audited 0.625, stronger than every seed. max-tokens 1536 per SKILL.md
# (truncation otherwise inflates/deflates ASR).
#
# Roles: victim=--target api:$VICTIM, judge=--judge-model
# deepseek/deepseek-v4-flash (attack.py passes judge-model straight to OpenRouter,
# bare model id, no api: prefix). No attacker role: attack.py applies
# deterministic string-transform DSL programs; no auxiliary LLM is queried
# (the LLM proposer lives in synthesize.py, not used here).
#
# Known risks: (a) v4-flash as the paper's G/B/U judge is a model substitution
# (paper used GPT-4) and over-counts AIM-persona prose by ~35% per the skill's
# GLM audit — trust the unified_judge ASR over the built-in one; (b) CharDropout
# uses a seeded RNG so the transform is deterministic, but target sampling still
# makes ASR vary run to run; (c) the default 5 goals is far below the canonical
# 10-prompt sample, so ASR is a smoke-test signal, not the paper number.
#
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
METHOD="$ROOT/XSkillLib/Single-turn/Multi-Strategy-Pool/2408.04811_h4rm3l/h4rm3l"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t h4rm3l_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t h4rm3l_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/h4rm3l_${VICTIM_SLUG}_cdaim_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column (skill
# loader takes rows[:sample] in file order, so exactly N_GOALS rows guarantees
# these N_GOALS)
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
cd "$METHOD"
"$PY" scripts/attack.py run \
  --target "api:$VICTIM" \
  --judge-model deepseek/deepseek-v4-flash \
  --dataset "$GOALS_CSV" --sample "$N_GOALS" \
  --programs synth_chardropout_aim \
  --max-tokens 1536 --workers 5 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
