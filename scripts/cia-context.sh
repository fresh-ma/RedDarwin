#!/usr/bin/env bash
# cia-context (Contextual Interaction Attack, 2402.09177) on $VICTIM (default
# deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default AdvBench.csv),
# strongest documented setting, then unified judge.
# Only the judged file is kept in results/.
#
# Setting basis: the skill is single-config; the only axis is token budget.
# results/RESULT_2026-06-26.md marks cia_context_v4flash_tokfix_20260626 (target/
# aux/judge all deepseek-v4-flash, max_tokens 2048) as the CANONICAL run; the
# earlier 1024-token run was archived for truncating 14/20 cases. Hence
# --max-tokens 2048 --judge-max-tokens 2048 (tag: mt2048).
#
# Known risks:
# - Paper's auxiliary was WizardLM-70B; SKILL.md documents substitution and the
#   script itself defaults --aux-model to deepseek-v4-flash, so v4-flash for aux
#   is the skill's own default. DeepSeek may still refuse to decompose some goals
#   (auxiliary_refused -> empty response -> attack failure, skipped by the judge).
# - This skill calls OpenRouter directly with bare model ids, so flags take
#   "deepseek/deepseek-v4-flash" WITHOUT the "api:" prefix other skills use.
# - The loader is JSONL-only (key `goal`); a temp JSONL is generated from
#   $GOALS_FILE. Rows are taken in file order (no shuffle), so
#   --sample-rows $N_GOALS pins exactly the first $N_GOALS.
# - --fallback-models is empty so every role (victim/aux/judge) stays strictly
#   on v4-flash; a transient provider error then fails the case instead of
#   falling back to another model.
# - Skill patched for this harness (scripts/cia.py, scripts/rerun.py): case
#   status "completed" -> "ok" (unified_judge skips any status not in {None,"ok"})
#   and single-target runs allowed (was: >=2 parameter sets required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Multi-turn/Decomposition/2402.09177_CIA/cia-context"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_JSONL="$(mktemp -t cia_goals_XXXXXX.jsonl)"
RAW_OUT="$(mktemp -t cia_context_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_JSONL" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/cia-context_${VICTIM_SLUG}_mt2048_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp JSONL with a `goal` key
"$PY" - "$GOALS_FILE" "$GOALS_JSONL" "$N_GOALS" <<'EOF'
import csv, json, sys
with open(sys.argv[1], newline='', encoding='utf-8') as f:
    goals = [r['request'] for r in csv.DictReader(f)][:int(sys.argv[3])]
with open(sys.argv[2], 'w', encoding='utf-8') as g:
    for i, goal in enumerate(goals):
        g.write(json.dumps({"goal": goal, "source_index": i}, ensure_ascii=False) + "\n")
EOF

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --allow-live \
  --data "$GOALS_JSONL" --sample-rows "$N_GOALS" \
  --targets "$VICTIM" \
  --aux-model deepseek/deepseek-v4-flash \
  --judge-model deepseek/deepseek-v4-flash \
  --fallback-models "" \
  --max-tokens 2048 --judge-max-tokens 2048 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
