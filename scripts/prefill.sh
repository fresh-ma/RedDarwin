#!/usr/bin/env bash
# Prefill-level Jailbreak (2504.21038, static assistant-prefill templates)
# on $VICTIM (default deepseek-v4-flash), first $N_GOALS goals of
# $GOALS_FILE (default AdvBench.csv), then unified judge.
# Only the judged file is kept in results/.
#
# Setting basis: the skill's canonical audited run
# (results/RESULT_2026-07-01.md + results/prefill_v4flash_static7_n14_t00_mt4096_20260628.json)
# used ALL 7 static prefill categories (default --attack-methods), temperature 0.0,
# max_tokens 4096 — the mt4096 budget is essential: SKILL.md warns low budgets are
# spent on v4-flash's hidden reasoning and return EMPTY content. This is the
# single canonical configuration; the paper's adaptive attacker-in-loop variant
# is kept as provenance only (closed-attacker policy).
#
# Known risks:
# - No attacker LLM role by design: the static-template attack uses fixed
#   vendored (prompt, prefill) pairs; only target and judge roles exist.
# - Judge flag is --judge-model and takes a BARE OpenRouter model id (no api:
#   prefix — the skill calls OpenRouter directly), while --target uses api:.
# - Prefill semantics depend on the provider honoring a trailing assistant
#   message; SKILL.md notes some providers ignore it (treat as capability
#   check, not method failure).
# - Canonical ASR is low (content_harmful score5 1/14) — a faithful
#   near-negative vs the paper's looser 3-judge majority vote.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Response-Prefill/2504.21038_Prefill/prefill"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t prefill_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t prefill_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/prefill_${VICTIM_SLUG}_static7_t00_mt4096_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with goal,target columns (the
# skill's read_goals() only accepts goal|Goal|behavior, and select() does a
# seeded shuffle before sampling; feeding exactly $N_GOALS rows guarantees the
# first $N_GOALS regardless of seed; target column feeds
# continuation_enforcement's prefill)
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
with open(sys.argv[1], newline='', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))[:int(sys.argv[3])]
with open(sys.argv[2], 'w', newline='', encoding='utf-8') as g:
    w = csv.writer(g)
    w.writerow(['goal', 'target'])
    w.writerows([r['request'], r['target']] for r in rows)
EOF

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --goals "$GOALS_CSV" --sample-rows "$N_GOALS" --seed 20260625 \
  --target "api:$VICTIM" \
  --judge-model deepseek/deepseek-v4-flash \
  --temperature 0.0 --max-tokens 4096 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
