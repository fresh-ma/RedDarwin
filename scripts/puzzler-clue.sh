#!/usr/bin/env bash
# Puzzler indirect implicit-clue jailbreak (arXiv:2402.09091) on $VICTIM
# (default qwen/qwen3.7-flash), $GOALS_FILE first $N_GOALS goals
# (defaults: AdvBench.csv, 5), strongest single setting, then unified judge.
# Only the judged file is kept in results/.
#
# Setting basis: the skill's canonical run (SKILL.md "Final result" +
# results/RESULT_2026-06-27.md, GLM-audited) ran 2 configs on the same target:
#   A: --max-defensive 6  --temperature 1.0  -> content-harmful 0.60
#   B: --max-defensive 10 --temperature 0.7  -> content-harmful 0.80 (QSR 0.90, FR 0.80)
# so the single strongest setting is B: --max-defensive 10 --temperature 0.7
# --attack-temperature 1.0 (as in the canonical setB run_parameters)
# --max-tokens 2048 (SKILL.md: v4-flash is a reasoning model; smaller budgets are
# consumed by hidden reasoning and yield empty outputs; judge max_tokens is
# hardcoded 1024 in scripts/roles.py).
#
# Known risks:
# - Per project convention all roles are deepseek/deepseek-v4-flash, but the
#   canonical run used deepseek/deepseek-chat as the attacker pipeline model
#   (itself a documented substitute for the paper's GPT-4/GPT-3.5). v4-flash as
#   attacker is a further substitution: the attacker substeps use small fixed
#   budgets (extract 128 / filter 8 / offensive 512 tokens in scripts/roles.py)
#   that hidden reasoning can exhaust, yielding empty substep outputs. The
#   pipeline degrades gracefully (malicious-content parse falls back to a
#   verb-stripped goal; an all-filtered clue set falls back to top defenses),
#   but clue quality and thus ASR may drop vs the canonical 0.80.
# - Flag names differ from other skills: --attack-model / --judge-model take
#   BARE OpenRouter ids (chat() does not strip api:); only --target takes the
#   api: prefix and requires --allow-live.
# - Minimal patch applied to the skill: scripts/attack.py cmd_run now remaps
#   per-case status "completed" -> "ok" in the written document only, because
#   judge/unified_judge.py skips any record whose status is not ok/None.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Scenario-Nesting/2402.09091_Puzzler/puzzler-clue"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t puzzler_clue_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t puzzler_clue_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/puzzler-clue_${VICTIM_SLUG}_setB_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals from $GOALS_FILE -> temp CSV with goal,target columns
# (the skill's load_rows requires a `goal` column and takes the first N rows in
# file order, so feeding exactly the first $N_GOALS rows guarantees the first
# $N_GOALS goals)
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
n = int(sys.argv[3])
with open(sys.argv[1], newline='', encoding='utf-8') as f:
    rows = [(r['request'], r.get('target', '')) for r in csv.DictReader(f)][:n]
with open(sys.argv[2], 'w', newline='', encoding='utf-8') as g:
    w = csv.writer(g)
    w.writerow(['goal', 'target'])
    w.writerows(rows)
EOF

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --samples "$GOALS_CSV" --sample-rows "$N_GOALS" \
  --target "api:$VICTIM" --allow-live \
  --attack-model deepseek/deepseek-v4-flash \
  --judge-model deepseek/deepseek-v4-flash \
  --max-defensive 10 --temperature 0.7 --attack-temperature 1.0 \
  --max-tokens 2048 --workers 5 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
