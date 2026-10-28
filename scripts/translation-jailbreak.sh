#!/usr/bin/env bash
# Translation Jailbreak (Yong et al. 2023, 2310.02446 Low-Resource-Language jailbreak)
# on $VICTIM (default qwen/qwen3.7-flash), $GOALS_FILE first $N_GOALS
# goals (defaults: AdvBench.csv, 5), then unified judge.
#
# Setting (strongest single config per skill results):
#   canonical tokfix run (results/RESULT_2026-06-26.md, audited in
#   GLM_REVIEW_tokfix_20260626.md): languages lrl only (zu,gd,hmn,gn = 4 cases/goal;
#   the paper's `en` identity control group is dropped — it is a baseline, not
#   part of the attack), temperature 0.0, --max-tokens 768 (tokfix: raised budget
#   so target outputs complete before judging). $N_GOALS goals x 4 languages
#   = 4*$N_GOALS cases.
#
# Translator: this machine has no Google Translate key, so instead of the
#   paper-exact `--translator project-api --translation-provider google` we use
#   the skill's native `--translator api` mode: an OpenRouter LLM performs both
#   forward and back translation. Default is deepseek/deepseek-v4-flash —
#   probe results 2026-07-29: v4-flash translates all four LRLs well, while the
#   uncensored dolphin-mistral-24b-venice-edition degenerates (repetition loops
#   on Hmong/Guarani, echoes source text on back-translation). Override via
#   TRANSLATOR_MODEL env var. --translation-max-tokens 2048 avoids reasoning-
#   token exhaustion empties seen at the 512 default; the skill now fails the
#   case on empty translation instead of forwarding it. Known residual risk:
#   v4-flash occasionally refuses IN the target language (undetectable cheaply)
#   and rare semantic slips (one negation flip observed).
#   Fidelity note: LLM translation is a model-substitution for Google MT; the
#   attack mechanism (low-resource-language transfer) is unchanged.
#
# Roles:
#   victim  = --target api:$VICTIM (parameterized; default api:deepseek/deepseek-v4-flash)
#   judge   = --judge-model deepseek/deepseek-v4-flash (skill flag takes a bare
#             OpenRouter model id, no api: prefix; paper BYPASS/REJECT/UNCLEAR rubric)
#   attacker/translator = dolphin-mistral-24b-venice-edition via --translator api
#
# Known risks:
#   - Requires OPENROUTER_API_KEY in $ROOT/.env (no Google key needed).
#   - Canonical audited ASR on v4-flash is 0.0125 (1/80): the 2023 LRL gap is
#     largely closed on this 2026 aligned model; expect near-zero ASR.
#   - unified_judge scores `model_output_text` (the low-resource-language output),
#     not `backtranslated_output_text`, so the final judge reads non-English text;
#     the skill's own per-case paper-rubric judge verdicts remain in the raw output.
#   - GLM_REVIEW header mentions gemini-2.5-flash as target, but the canonical JSON's
#     target field and RESULT_2026-06-26.md both say deepseek/deepseek-v4-flash;
#     we follow the JSON/RESULT (v4-flash).
# Only the judged file is kept in results/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Language-Transfer/2310.02446_LRL/translation-jailbreak"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
TMPD="$(mktemp -d)"
RAW_OUT="$TMPD/raw.json"
GOALS_JSON="$TMPD/goals.json"
trap 'rm -rf "$TMPD"' EXIT
JUDGED_OUT="$RESULTS/translation-jailbreak_${VICTIM_SLUG}_lrl-en-tokfix_${N_GOALS}x_${STAMP}.judged.json"

TRANSLATOR_MODEL="${TRANSLATOR_MODEL:-deepseek/deepseek-v4-flash}"

# Preflight: the LLM translator goes through OpenRouter (the skill's walk-up
# loader reads $ROOT/.env). Fail fast with a clear message.
if [ -z "${OPENROUTER_API_KEY:-}" ] && ! grep -qE '^OPENROUTER_API_KEY=\S' "$ROOT/.env" 2>/dev/null; then
  echo "ERROR: OPENROUTER_API_KEY is not set and missing from $ROOT/.env" >&2
  exit 1
fi

# 0) goals CSV (columns: request,target) first $N_GOALS goals -> temp goals JSON.
#    The skill loader accepts the CSV's `request` column, but --sample N uses a
#    seeded shuffle, so "first N" is only guaranteed by pre-slicing the dataset.
"$PY" - "$GOALS_FILE" "$GOALS_JSON" "$N_GOALS" <<'EOF'
import csv, json, sys
src, dst, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
with open(src, newline='', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))
goals = [{"id": str(i), "goal": r["request"].strip()} for i, r in enumerate(rows[:n])]
json.dump(goals, open(dst, "w"), ensure_ascii=False)
EOF

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --goals "$GOALS_JSON" \
  --target "api:$VICTIM" \
  --translator api --translator-model "$TRANSLATOR_MODEL" \
  --judge-model deepseek/deepseek-v4-flash \
  --languages lrl \
  --seed 20260626 \
  --temperature 0.0 --top-p 0.0 \
  --max-tokens 768 --translation-max-tokens 2048 --request-delay 0.5 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
