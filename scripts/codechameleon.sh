#!/usr/bin/env bash
# CodeChameleon (2402.16717) attack on $VICTIM (default qwen/qwen3.7-flash),
# first $N_GOALS goals of $GOALS_FILE (default bench/AdvBench.csv, first 5),
# canonical tokfix setting (rules=reverse,binary_tree × template=code × include-system,
# max-tokens 2048), then unified judge.
# Only the judged file is kept in results/.
#
# Setting 依据: skill 的 canonical 结果 results/codechameleon_v4flash_16x2_tokfix_20260626.json
#   (+ RESULT_2026-06-26.md, audited ASR 0.75) 使用 rules=[reverse,binary_tree]、
#   template=code、include_system=True、max_tokens=2048(tokfix 版,避免 payload 截断)。
#   本脚本复刻该配置,仅把 16 goals 换成 $GOALS_FILE 前 $N_GOALS 条(默认 AdvBench
#   前 5 条,5 goals × 2 rules = 10 cases)。
#
# 已知风险 / 说明:
#   - 该 skill 无 attacker(辅助LLM)角色: payload 由确定性加密 + 固定模板生成,无需辅助模型。
#   - victim(--target)需要 api: 前缀; skill 内置的 Qi-2023 judge(--judge-model)直连
#     OpenRouter,用裸模型 id(不带 api: 前缀)。论文官方 judge 是 GPT-4,但 OpenRouter
#     openai/* 会 403 有害判定 prompt,故按 SKILL.md 记录用 deepseek-v4-flash 替代
#     (与 canonical 结果一致)。最终评分仍以 unified_judge 为准。
#   - 数据集: skill 的 loader(cases.py read_rows)原生支持 request 列,--limit "$N_GOALS"
#     在 shuffle 之前确定性取前 N_GOALS 行(不传 --sample,避免 seeded shuffle)。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Code-Encapsulation/2402.16717_CodeChameleon/codechameleon"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAW_OUT="$(mktemp -t codechameleon_raw_XXXXXX.json)"
trap 'rm -f "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/codechameleon_${VICTIM_SLUG}_2r_tokfix_${N_GOALS}x_${STAMP}.judged.json"

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --target "api:$VICTIM" \
  --judge --judge-model deepseek/deepseek-v4-flash \
  --goals "$GOALS_FILE" --limit "$N_GOALS" \
  --rules reverse,binary_tree --template code \
  --max-tokens 2048 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
