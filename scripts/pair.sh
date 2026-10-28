#!/usr/bin/env bash
# PAIR (2310.08419, paper-faithful port) on $VICTIM (default
# deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv, first 5), then unified judge.
# Only the judged file is kept in results/.
#
# Setting basis: the skill's canonical audited run
# (results/RESULT_2026-06-27.md + results/pair_v4flash_s2i3_tok2048_rerun.json)
# used streams=2 x iterations=3 x strategies roleplay,logical with
# target_max_tokens=2048 (the tokfix; the default 150 truncates harmful
# payloads) and judge_max_tokens=64 (the default 10 starves the reasoning
# judge into empty/under-rated verdicts). That GLM-audited configuration is
# the single strongest documented setting, so it is used verbatim.
#
# Known risks:
# - The canonical run's attacker was gryphe/mythomax-l2-13b (weakly aligned,
#   chosen because it won't refuse the jailbreak-writer role). Per project
#   convention the attacker here is api:deepseek/deepseek-v4-flash instead;
#   earlier deepseek-chat attacker runs showed 0/180 refusals, but a parse or
#   refusal failure ends a turn via skipped_attacker_failed.
# - On a v4-flash target the audited judge10 ASR was 0.0 (target robust);
#   low ASR is expected, not a bug.
# - attack_max_tokens keeps the skill default 500 (canonical run did not
#   override it); v4-flash attacker JSON may rarely truncate.
# - judge flag is --judge (not --judge-model); all three roles are v4-flash.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
source "$ROOT/scripts/lib/common.sh"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Persuasion/2310.08419_PAIR/pair"
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
GOALS_CSV="$(mktemp -t pair_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t pair_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/pair_${VICTIM_SLUG}_s2i3tok2048_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with goal,target columns (the
# skill's load_cases shuffles before sampling and does not accept a `request`
# column, so feeding exactly N_GOALS normalized rows guarantees the first
# N_GOALS and gives the official AdvBench target prefix to the judge prompt)
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
  --target "api:$VICTIM" \
  --judge api:deepseek/deepseek-v4-flash \
  --streams 2 --iterations 3 --strategies roleplay,logical \
  --target-max-tokens 2048 --judge-max-tokens 64 \
  --case-workers "$GOAL_WORKERS" \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
