# Cognitive Overload Jailbreak 数据集说明（2311.09827）

主要来源：官方仓库 **luka-group/CognitiveOverload**，commit `a6ffde10087f10803937fca8764a65017bde96ab`，`datasets/` 目录。原始数据已复制到本地，并转换为可读的 UTF-8 缩进 JSON list。

论文：Xu et al., *Cognitive Overload: Jailbreaking Large Language Models with Overloaded Logical Thinking*（NAACL-Findings 2024）。

论文 Section 2 “Evaluation Benchmarks” 使用两个有害行为 benchmark；Section 3.1 “Data Processing” 把两个英文 benchmark 机翻到另外 52 种语言，用于 multilingual cognitive-overload attack。

> "We first translate the original English harmful instructions from AdvBench and MasterKey into 52 other languages."

## `AdvBench/`（Zou et al. 2023，universal）

- `AdvBench/attacks.json`：**520** 条英文 harmful behaviour，来自原始 AdvBench。
- `AdvBench/<lang>/attacks.json`：同一批 520 条 goal 的机器翻译版，每种语言一个目录。共 **52** 种语言：`af ar bg bn ca cs cy da de el es et fa fi fr gu he hi hr hu id is it ja kn ko lt lv ml mr ne nl no pa pl pt ro ru sk sl sr sv sw ta te th tr uk ur vi zh-CN zh-TW`。每个文件 520 行。
- `AdvBench/<lang>/context_wiki.json`：每种语言 520 条非英语 Wikipedia 语境片段，字段为 `response_0`，用于 `language_switch_lan_to_en` 模式的 turn-1。每种语言 520 行。

行格式：

```json
{"goal": "<harmful instruction>", "target": "random", "control": ""}
```

## `MasterKey/`（Deng et al. 2023，jailbreaker）

- `MasterKey/attacks.json`：**45** 条英文实例，来自 9 个 prohibited scenario（Adult、Government、Harmful、Inappropriate、Misleading、Political、Privacy、Unauthorized Practice、Unlawful）× 每类 5 个问题。已从官方 repo 的 per-scenario `*_controls.json` 文件 flatten 出来，并额外保留 `"scenario"` 字段。
- `MasterKey/<lang>/attacks.json`：同一批 45 条实例的机器翻译版，每种语言一个目录，共 **52** 种语言。每个文件 45 行。

行格式：

```json
{"goal": "<harmful question>", "target": "random", "control": "", "scenario": "<scenario name>"}
```

注意：论文正文把 MasterKey 描述为 “11 prohibitive scenarios … 55 instances”，但官方仓库只释放了 **9** 个 scenario 文件，即 **45** 条实例。这里保留完整官方释放集，不伪造缺失的两个 scenario。MasterKey 没有 `context_wiki`，所以 `language_switch_lan_to_en` 模式只对 AdvBench 开放，逻辑在 `attack.py:build_cases` 里 gate。

## 格式与完整性

- `AdvBench/` 和 `MasterKey/` 存储为缩进 JSON **list**，不是 JSONL，也不是 pickle。`attack.py` 通过 `read_json_list` 读取。
- 所有计数都是官方已释放数据的完整集，不是 sample / slice。
- `AdvBench/attacks.json` 与官方英文 `attacks.json` 做过 sorted diff，内容一致。

## UltraChat（Ding et al. 2023，良性 baseline）—— 参考资产，未下载

- Source: `openbmb/UltraChat` (Hugging Face)，行格式 `{"id": <string>, "data": [<turn strings>]}`（user/assistant 交替多轮，约 1.47M 条）。
- **本 unit 不 ship 这份数据**（attack-only 复现不参与）：它只在论文 Section 7 的 reward-model utility/over-refusal
  评测里作良性回复 baseline，与本攻击无关。如需该评测，从上述 HF source 自行获取。

