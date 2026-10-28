---
name: cia-context
description: "Contextual Interaction Attack (2402.09177): black-box multi-turn jailbreak. Auxiliary LLM turns a harmful goal into an epsilon ladder; each epsilon is sent as a separate target turn; prior target answers become context; final response is judged by prefix-bypass and PAIR/ChatGPT-score rubric."
paper_id: "2402.09177_multi-turn-contextual-jailbreak"
attack: "contextual_interaction_attack"
access: "black_box_api"
execution_mode: ["inspect", "live_target_run"]
evidence_level: "live_target_run"
metadata:
  payload_contract:
    input: "One harmful goal plus the auxiliary model's epsilon ladder."
    output: "A multi-turn user/assistant transcript whose final user message is the transformed goal."
    retained_state: "The epsilon ladder and every target reply; replies are retained as dialogue context."
    feedback_dependency: "target replies supply context but do not alter the already-generated ladder"
    composition_status: "freeze_then_replay"
---

# CIA Contextual Interaction Attack

## What

这篇的 runnable unit 是一个黑盒多轮 jailbreak。payload 不是“整个对话”，而是
AdvBench 里的原始 harmful goal。攻击脚本先让 auxiliary LLM 把这个 payload 改写
成一串看起来较无害的 `epsilon_sequence`；最后一个 epsilon 是真正的伪装攻击查询。
input carrier 是完整多轮 chat transcript：每个 `epsilon_i` 单独发给 target，并把
target 自己的回答 `alpha_i` 留在上下文里。

## Files

- `data/advbench_full_520.jsonl`：AdvBench 全量 520 条（Zou et al. 2023），所有子集的源头超集。
- `data/advbench_pair_50.jsonl`：完整 50 条 PAIR-curated AdvBench Subset（论文 §4.1 真实数据集；520 的子集；新 run 的默认数据源）。
- `data/advbench_subset_10.jsonl`：10 条 sample slice（AdvBench 前 10，历史 run 用的 slice，保存结果 provenance）。
- `scripts/attack.py`：核心 CLI 入口（auxiliary decompose / multi-turn target / dual judge）+ `run` / `inspect` 命令。
- `scripts/cia.py`：攻击编排与 paper-verbatim prompts；供 CLI 与辅助脚本共同导入。
- `scripts/rerun.py`：单一 rerun 驱动（DeepSeek V4 Flash target+judge 默认 + fallback 链；>=2 config = auxiliary 模型）。合并了旧的 `rerun_v4flash.py` / `rerun_v4flash_tokfix.py`。
- `scripts/annotate_result.py`：从 raw run 生成 append-only audited/normalized 结果（后处理，单独脚本）。
- `results/`：历史 live target/judge 输出。
- `references/legacy-code/`：旧 `code/` 目录的报告和 check，保留 provenance。
- `references/SOURCE_STATUS.md`：论文未声明 paper-owned 官方实现；本 unit 是 paper-derived。
- `environment.md`：环境和密钥说明。

## Run

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/cia.py` walks up to find it) — no per-skill `.env`,
no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

无网络、无 API key 的静态 preflight：

```bash
cd XSkillLib/Multi-turn/Decomposition/2402.09177_CIA/cia-context
$PY scripts/attack.py inspect
```

真实运行（显式打开 live gate；默认 DeepSeek V4 Flash + fallback 链，从 50 条里 sample 10）：

```bash
cd XSkillLib/Multi-turn/Decomposition/2402.09177_CIA/cia-context
$PY scripts/attack.py run \
  --allow-live \
  --sample-rows 10 \
  --targets deepseek/deepseek-v4-flash,qwen/qwen-2.5-7b-instruct \
  --aux-model deepseek/deepseek-v4-flash \
  --judge-model deepseek/deepseek-v4-flash \
  --fallback-models qwen/qwen-2.5-72b-instruct \
  --max-tokens 2048 \
  --judge-max-tokens 2048
```

Rerun 驱动（target+judge 固定为 DeepSeek，config 轴 = auxiliary 模型，带 fallback）：

```bash
$PY scripts/rerun.py --sample-rows 10 --max-tokens 2048
```

`--fallback-models` 指定的模型会在主模型失败时按顺序尝试；如果整条链都失败，该 case 记为 `provider_error`（攻击失败）。默认会写入 `results/cia_context_<params>_<timestamp>.json`。每条 case 都包含：

- `goal` / `payload.payload_original`：原始 payload。
- `auxiliary.epsilon_sequence` / `payload.payload_transformed`：payload 如何被改写。
- **`model_input_messages`（canonical 输入）**：完整 OpenAI `[{role, content}]` 对话——system + 交替的 epsilon→user / alpha→assistant，结尾停在最后一个 user 触发查询上。由 `transcript_from_turns()`/`input_messages_from_turns()` 从 `turns` 派生。
- **`model_output_text`（canonical 输出）**：最终 harmful 回复（= `final_response`）。
- `turns` / `payload.input_carrier`：补充的 per-turn 明细（每轮 epsilon/alpha + finish_reason/usage）。
- `final_response` / `verdicts`：target 效果和 judge 结果。

历史 result JSON 可用 `$PY scripts/convert_result_messages.py results/*.json` 回填 `model_input_messages` + `model_output_text`（幂等）。

## Evidence

- `results/cia_context_run_20260611_ready.json`：20 cases，Llama-3.1-8B + Qwen-2.5-7B target，0 provider errors，content-harmful ASR = 0/20。
- `results/cia_context_v4flash_tokfix_20260626_audited.json`：canonical audited result，派生自 token-fix raw run，20 cases，0 provider errors，raw content-harmful ASR = 2/20，GLM-audited ASR = 1/20，并补齐 per-case `payload`。
- `results/cia_context_v4flash_tokfix_20260626.json`：原始 token-fix raw run，保留 provenance。
- `results/cia_mistral_susceptible_20260627.json`：6-case susceptibility probe，3 provider errors，不作为 completion evidence。

## Notes

论文原始 auxiliary 是 WizardLM-70B；当前脚本暴露 `--aux-model` 替换。论文主指标有人审，代码里可复现的两个 judge 是 prefix matching 和 PAIR/ChatGPT-score rubric。不要把 `refusal_bypass` 当成有害成功率；它只表示没有明显拒绝前缀。
