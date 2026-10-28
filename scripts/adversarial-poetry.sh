#!/usr/bin/env bash
# Adversarial Poetry (2511.15304) attack on $VICTIM
# (default qwen/qwen3.7-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/AdvBench.csv, N_GOALS default 5), canonical setting
# (target_max_tokens 1536,
# the tokfix/canonical config per results/RESULT_2026-06-27.md), then unified judge.
# Only the judged file is kept in results/.
#
# Setting 依据: skill 的 RESULT_2026-06-27.md 标注 target_max_tokens=1536 的
# run 为 canonical（700-token 版本会截断 v4-flash 的推理，仅作 provenance 保留）;
# 该 canonical run 本身即 target = transform = deepseek-v4-flash。
#
# 已知风险:
# - 论文的 transform model 是 deepseek-r1, 这里按 benchmark 要求统一用
#   deepseek-v4-flash（与 skill 自己的 canonical run 一致, 但偏离论文 sec 5.2）。
# - 论文/skill 默认 judge 是 3 个不同 open 模型的 2-of-3 ensemble; 这里按
#   benchmark 要求 3 票全部用 deepseek-v4-flash, ensemble 多样性退化为单模型
#   3 次投票（flag 只接受裸 OpenRouter model id, 不带 api: 前缀）。
# - skill 的 loader 不认 AdvBench 的 request 列, 且采样前会 seeded shuffle;
#   故脚本内嵌 python 把 $GOALS_FILE 前 $N_GOALS 条 request 写成带 goal 列的
#   临时 CSV, 恰好 N_GOALS 行使 shuffle 不影响选取。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Stylistic-Obfuscation/2511.15304_AdversarialPoetry/adversarial-poetry"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
# NOTE: BSD mktemp only replaces trailing X's; `mktemp -t foo_XXXXXX.csv` would
# append the random suffix after ".csv", producing a path whose extension the
# skill's dataset loader rejects. Use a temp dir with proper extensions instead.
TMPDIR_RUN="$(mktemp -d -t adversarial_poetry)"
GOALS_CSV="$TMPDIR_RUN/goals.csv"
RAW_OUT="$TMPDIR_RUN/raw.json"
trap 'rm -rf "$TMPDIR_RUN"' EXIT
JUDGED_OUT="$RESULTS/adversarial-poetry_${VICTIM_SLUG}_mt1536_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column (skill
# shuffles before sampling, so feeding exactly N_GOALS rows guarantees these
# goals regardless of seed)
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
with open(sys.argv[1], newline='', encoding='utf-8') as f:
    goals = [r['request'] for r in csv.DictReader(f)][:int(sys.argv[3])]
with open(sys.argv[2], 'w', newline='', encoding='utf-8') as g:
    w = csv.writer(g)
    w.writerow(['goal'])
    w.writerows([goal] for goal in goals)
EOF

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" -u scripts/attack.py \
  --dataset "$GOALS_CSV" \
  --target "api:$VICTIM" \
  --transform-model api:deepseek/deepseek-v4-flash \
  --judges deepseek/deepseek-v4-flash,deepseek/deepseek-v4-flash,deepseek/deepseek-v4-flash \
  --sample "$N_GOALS" --seed 260626 \
  --target-max-tokens 1536 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
