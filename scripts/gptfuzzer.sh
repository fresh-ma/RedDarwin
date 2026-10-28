#!/usr/bin/env bash
# GPTFuzzer (paper-local port, 2309.10253) on $VICTIM
# (default qwen/qwen3.7-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/AdvBench.csv, N_GOALS default 5), then unified judge.
# Only the judged file is kept in results/.
#
# Setting basis: the skill's live gate (SKILL.md "Completed live gate 2026-06-10")
# ran two settings; settingA was clearly the strongest (RoBERTa ASR 54/60=0.90 vs
# settingB 25/40=0.625), so we use settingA: --seed-templates-limit 4
# --iterations 3 --energy 1 --max-queries 80, default MCTS params
# (ratio 0.5 / alpha 0.1 / beta 0.2, concatenate on), seed 20260609.
# --max-tokens 1536 follows the canonical v4-flash run (RESULT_2026-06-27.md) to
# avoid truncating harmful completions (default 256 was tuned for deepseek-chat).
#
# Known risks:
# - attacker role = mutator LLM, flag is --mutator-model with a BARE model id
#   (no api: prefix; only --target takes api:<model>). We use v4-flash per
#   project convention, but the canonical run used the weakly-aligned
#   gryphe/mythomax-l2-13b because a hosted aligned model may refuse to mutate
#   jailbreak templates (mutator_calls status != ok); SKILL.md also notes the
#   OpenRouter openai/* route 403s on mutator prompts. Mutator refusals degrade
#   ASR but do not crash the run (the parent seed template is reused).
# - this skill has NO LLM judge role by design: the judge is the paper's
#   official finetuned RoBERTa classifier hubert233/GPTFuzz, run in-process on
#   CPU (first run downloads ~500MB from HuggingFace — NOT yet in the local HF
#   cache on this machine, so the first run needs network access to HF;
#   requires transformers==4.46.3, already pinned in the shared venv).
#   NOTE: this machine's direct TLS to huggingface.co is unreliable (SSL EOF),
#   so default HF_ENDPOINT to hf-mirror.com for any future cache miss (the
#   model is pre-warmed in the local HF cache as of 2026-07-28; huggingface_hub
#   also falls back to the cache when the endpoint is unreachable).
#   unified_judge re-scores with v4-flash afterwards regardless.
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
# models are already in the local HF cache; skip hub HEAD checks (they hang
# for minutes on retries when the network is flaky) and load from cache.
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
# - loader accepts a `goal` CSV column but shuffles before sampling
#   (load_questions, seeded RNG), so we feed a temp CSV with exactly the first
#   $N_GOALS goals of $GOALS_FILE; shuffling N rows and taking N keeps them all.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Multi-Strategy-Pool/2309.10253_GPTFuzz/gptfuzzer"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_CSV="$(mktemp -t gptfuzzer_goals_XXXXXX.csv)"
RAW_OUT="$(mktemp -t gptfuzzer_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/gptfuzzer_${VICTIM_SLUG}_settingA_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column (loader
# shuffles before sampling, so feeding exactly N_GOALS rows guarantees the
# first N_GOALS goals)
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
  --questions "$GOALS_CSV" --sample-rows "$N_GOALS" --seed 20260609 \
  --seed-templates-limit 4 \
  --target "api:$VICTIM" \
  --mutator-model deepseek/deepseek-v4-flash \
  --iterations 3 --energy 1 --max-queries 80 \
  --max-tokens 1536 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
