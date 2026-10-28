#!/usr/bin/env bash
# Cognitive Overload (2311.09827) on $VICTIM (default qwen/qwen3.7-flash),
# first $N_GOALS goals of $GOALS_FILE (default bench/AdvBench.csv, first 5),
# veiled_expression mode (plain variant), then unified judge.
#
# Setting 依据: canonical result (skill results/RESULT_2026-06-29.md + GLM audit) —
# veiled_expression(--paraphraser-variant plain) is the ONLY config with genuine
# on-goal harm (audited ASR 0.20 vs mistral-nemo; monolingual-sw and effect-to-cause
# both audited 0.00). Canonical run used --max-tokens 1024; we use 2048 per the CLI's
# own guidance (>=2048 or truncation makes the judge under-count).
#
# 数据集: the skill loads its own shipped data/AdvBench/attacks.json (--dataset only
# accepts AdvBench/MasterKey, no custom CSV flag); verified offline that its first
# goals are identical to bench/AdvBench.csv's first `request` rows, so
# --sample "$N_GOALS" --start-index 0 pins the first $N_GOALS goals. GOALS_FILE must
# keep the default bench/AdvBench.csv for this equivalence to hold (otherwise it only
# feeds the output filename).
#
# 角色: victim=--target, attacker(辅助LLM)=--paraphraser-model (veiled rewrite),
# judge=--judge-model (skill 内置 content-harm guard, 裸模型 id 不带 api: 前缀) +
# unified_judge (默认 api:deepseek/deepseek-v4-flash)。全部 v4-flash。
#
# 已知风险:
# - --paraphraser-fallback-models 默认是 api:mistralai/mistral-nemo，这里覆盖为
#   v4-flash 以遵守全 v4-flash 约定；代价是 primary 拒绝后 fallback 是同一模型，
#   大概率同样拒绝 -> 该 goal 的 veiled case 被丢弃并由后续 goal 顶上
#   (build_cases top-up)，此时样本不再严格等于"前 N_GOALS 条"。stderr 会打印丢弃数。
# - veiled_expression 每 case 先调 paraphraser，再调 target：5 case 约 10+ 次 API 调用。
# - 对 attack.py 打了最小补丁: 成功 status 由 "completed" 改为 "ok"（否则
#   unified_judge 全部跳过）；skill 自身 metrics 过滤已同步更新。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Reasoning-Manipulation/2311.09827_CognitiveOverload/cognitive-overload"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t cognitive_overload_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/cognitive-overload_${VICTIM_SLUG}_veiled-plain_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API keys come from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run-api \
  --dataset AdvBench \
  --modes veiled_expression --paraphraser-variant plain \
  --sample "$N_GOALS" --start-index 0 \
  --target "api:$VICTIM" \
  --paraphraser-model api:deepseek/deepseek-v4-flash \
  --paraphraser-fallback-models api:deepseek/deepseek-v4-flash \
  --judge-model deepseek/deepseek-v4-flash \
  --max-tokens 2048 \
  --temperature 0.0 --request-delay 0.3 \
  --run-out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
