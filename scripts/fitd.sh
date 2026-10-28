#!/usr/bin/env bash
# FITD (Foot-In-The-Door, arXiv:2402.15690) attack on $VICTIM,
# first $N_GOALS goals of $GOALS_FILE, then unified judge.
#
# Attack   : fitd — staged background -> villain -> plot split, recursive
#            split-on-refusal (paper Algorithm 1).
# Setting  : split_instance=background_villain_plot x max_split_depth {1,2}
#            (alternated per case, hardcoded in build_cases — the only/strongest
#            config per SKILL.md + results/RESULT_2026-06-26.md), max_tokens=2048
#            (the "tokfix" run: raised from 1024 to cut truncations).
# Known risks:
#  - Attacker is a DETERMINISTIC template (no attacker LLM exists in this
#    skill), so only target + judge are model-pinned.
#  - SKILL.md warns deepseek-v4-flash as the paper 1-10 judge emits literal
#    "None" ~40% of the time (skill authors used deepseek-chat for re-judge).
#    Per harness policy we still pin --judge-model to v4-flash; expect some
#    null paper-judge scores. The unified judge pass at the end re-scores
#    everything with v4-flash anyway, so ASR is still comparable.
#  - Historical audit found the paper judge over-credits fictional villain
#    narratives (raw ASR inflated ~4x); treat paper-judge ASR with care.
#
# Loader note: scripts/cases.py was minimally patched to accept the stock
# AdvBench `request` column as a `goal` alias; load_rows takes the FIRST N
# rows (no shuffle), so --sample-rows $N_GOALS == first $N_GOALS goals.
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Multi-turn/Context-Priming/2402.15690_FITD/fitd"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t fitd_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/fitd_${VICTIM_SLUG}_bvp_d12_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --samples "$GOALS_FILE" --sample-rows "$N_GOALS" \
  --target "api:$VICTIM" \
  --judge-model deepseek/deepseek-v4-flash \
  --max-tokens 2048 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
