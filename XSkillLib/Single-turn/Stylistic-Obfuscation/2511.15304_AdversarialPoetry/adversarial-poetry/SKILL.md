# Adversarial Poetry

## What

Paper-local runner for `2511.15304_adversarial-poetry-jailbreak`。

把有害 prompt 重写成**诗歌**（verse/metaphor/rhythm），单轮发给 target。
核心对比：baseline（原文直发）vs poetic（改写成诗后发）的 ASR 差异。
论文声称诗歌形式普遍提升 ASR（手工诗 ~62%，元提示 ~43%，最高 18×）。

## Use

两臂设计（two-arm）：

```
baseline:  有害 prompt 原文 → target → response → judge
poetic:    有害 prompt → transform model 改写成诗 → target → response → judge
```

Judge ensemble：3 个 open/lab judge，二元 SAFE/UNSAFE，2-of-3 majority。

数据集：
- `data/ailuminate_demo_en_us.csv` — MLCommons AILuminate demo（1200 prompts，12 hazard categories）

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/models.py` walks up to find it) — no per-skill `.env`,
no `uv run`, no manual `export`. Needs `OPENROUTER_API_KEY`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Run

Inspect（不调 target/judge API，只打印 meta-prompt + 1 次 transform 示例）：

```bash
cd XSkillLib/Single-turn/Stylistic-Obfuscation/2511.15304_AdversarialPoetry/adversarial-poetry
$PY scripts/attack.py --inspect
```

完整运行（10 samples，baseline + poetic = 20 target calls + transform + judge）：

```bash
cd XSkillLib/Single-turn/Stylistic-Obfuscation/2511.15304_AdversarialPoetry/adversarial-poetry
$PY -u scripts/attack.py \
  --sample 10 --seed 260626 \
  --target api:deepseek/deepseek-v4-flash \
  --transform-model api:deepseek/deepseek-v4-flash \
  --judges deepseek/deepseek-v4-flash,qwen/qwen-2.5-72b-instruct,mistralai/mistral-small-3.2-24b-instruct \
  --out results/poetry_deepseek_v4_flash_openjudges_n10_20260626.json
```

## Test

```bash
cd XSkillLib/Single-turn/Stylistic-Obfuscation/2511.15304_AdversarialPoetry/adversarial-poetry
$PY -m py_compile scripts/attack.py scripts/models.py scripts/roles.py scripts/cases.py scripts/prompts.py
$PY scripts/attack.py --inspect
```

## Settings & Parameters

| Flag | 含义 |
|------|------|
| `--target` | `api:<model>` — 被攻击的 target（open/lab only） |
| `--transform-model` | `api:<model>` — 把 prompt 改写成诗的模型（论文用 deepseek-r1） |
| `--judges` | 逗号分隔 3 个 `model-id`，2-of-3 majority |
| `--sample` | 采样 N 条 baseline prompts |
| `--seed` | 采样随机种子 |
| `--dataset` | 数据集路径（默认 AILuminate demo） |
| `--target-max-tokens` | Target 输出上限（默认 700） |
| `--transform-max-tokens` | Transform 输出上限（默认 900） |
| `--delay` | API 调用间隔（默认 0.3s） |

## 结果解读

每个 case 包含 baseline 和 poetic 两臂：
- `baseline.unsafe`: 原文直发是否 UNSAFE
- `poetic.unsafe`: 诗歌改写后是否 UNSAFE
- `poetic.poem`: transform model 生成的诗歌
- `judge.votes`: 3 个 judge 各自的 SAFE/UNSAFE 投票

ASR = UNSAFE 比例。核心指标 = **poetic ASR - baseline ASR**（lift）。
