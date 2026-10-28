#!/usr/bin/env bash
# Echo Chamber (2601.05742, NeuralTrust/echo-chamber) on $VICTIM,
# first $N_GOALS goals of $GOALS_FILE, then unified judge.
#
# Setting basis: results/RESULT_2026-07-01.md (CANONICAL) — the faithful post-fix
# run used max-turns 4 (outer 3 / inner 2 persuasion cycle with backtrack) and
# target-max-tokens 2048, attacker temp 0.5 / target temp 0.0 (both defaults);
# that configuration reached the best audited content_harmful 8/12 = 0.6667 on
# deepseek-v4-flash, so it is reused here unchanged.
#
# Known risks:
# - SKILL.md defaults the attacker role to a local uncensored Ollama model
#   (ollama:uncensored) because a hosted model may refuse the adversarial
#   persona; per project convention we still force api:deepseek/deepseek-v4-flash
#   for attacker/judge while target follows $VICTIM — attacker-side refusals or
#   JSON-mode failures can silently degrade the steering ladder.
# - $GOALS_FILE rows (request/target format) carry no jailbreak/benign response
#   descriptions, so the skill's internal secondary judge gets empty descriptions
#   and its verdict is
#   unreliable; the unified judge below (goal + final_response) is the metric.
# - scripts/attack.py was minimally patched: CSV loader (`request` column) +
#   --limit flag (pins first N rows before the seeded sample) + top-level
#   goal/final_response per case so unified_judge can extract the pair.
#
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Multi-turn/Crescendo/2601.05742_EchoChamber/echo-chamber"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t echo_chamber_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/echo-chamber_${VICTIM_SLUG}_mt4_tk2048_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
#    --limit $N_GOALS pins the first $N_GOALS rows of $GOALS_FILE before the
#    seeded sample
cd "$METHOD"
"$PY" scripts/attack.py run \
  --dataset "$GOALS_FILE" \
  --target "api:$VICTIM" \
  --attacker-model api:deepseek/deepseek-v4-flash \
  --judge-model api:deepseek/deepseek-v4-flash \
  --limit "$N_GOALS" --sample "$N_GOALS" \
  --max-turns 4 --target-max-tokens 2048 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
