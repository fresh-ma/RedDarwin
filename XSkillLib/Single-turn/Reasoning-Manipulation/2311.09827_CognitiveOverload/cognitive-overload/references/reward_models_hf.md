# Section 7 提到的 Reward Models

访问时间：2026-06-29。

论文 Section 7 里的两个 reward model 只作为**额外 evaluator** 使用，不是攻击模型，也不是 target LLM。它们的作用是给模型回复打一个 human-preference / helpfulness 分数，然后比较三类回复：

- UltraChat 的正常良性回复；
- AdvBench 的有害回复；
- ChatGPT 在 cognitive-overload 攻击下生成的回复。

所以这里的分数应该理解成“人类偏好 / 有用性 reward”，不能直接等同于安全分类器或 toxicity detector。

## 为什么它们看起来能做“有害性相关评分”

你的直觉是对的：这两个模型本质上就是“判断哪个答案更好一点”的工具。它们不是直接训练成：

```text
harmfulness(prompt, answer) = 0.92
```

它们训练的是一个 reward 函数：

```text
score(prompt, answer)
```

训练数据通常是 pairwise preference：

```text
prompt: 用户问题
chosen: 人类更偏好的回答
rejected: 人类不偏好的回答
```

训练目标是让模型学会：

```text
score(prompt, chosen) > score(prompt, rejected)
```

如果训练数据里包含 HH-RLHF 这类 harmlessness preference，那么很多样本会长得像：

```text
prompt: 用户提出危险请求
chosen: 拒绝危险请求，并给安全替代建议
rejected: 直接满足危险请求
```

模型反复看到这种 pair 后，就会间接学到：

```text
score(安全拒绝 / 安全替代建议) > score(直接危险回答)
```

这就是它们为什么能作为“有害性相关 proxy signal”。但这个 proxy 不等于真正的 harm label。模型输出的是“这个回答多像人类偏好的回答”，不是“这个回答有多有害”。

因此更准确的叫法应该是：

- `preference reward score`
- `helpfulness / harmlessness proxy`
- `human-preference scorer`

不应该直接叫“有害性评分器”。如果要做正式 harmfulness 判断，还需要额外的 harm judge / goal-fidelity judge / 内容审计。

## `stanfordnlp/SteamSHP-flan-t5-xl`

来源：https://huggingface.co/stanfordnlp/SteamSHP-flan-t5-xl

- 模型：FLAN-T5-xl，约 3B 参数。
- HF 标签：preference model、RLHF、NLG evaluation、English。
- 训练数据：Stanford Human Preferences Dataset（SHP）和 Anthropic HH-RLHF 的 helpfulness 部分。
- 模型卡报告水平：在能截断到输入长度限制内的 SHP + Anthropic helpfulness 测试域上，unweighted average accuracy 为 **72.8%**。
- 打分方式：把要评分的回复放在 `RESPONSE A`，把 `RESPONSE B` 设为空输入 `.`，然后取模型输出 token `A` 的概率或 logit 作为这个回复的 reward score。
- 实际成本：PyTorch 权重分成两个 shard，约 **9.45GB** 和 **1.95GB**；本地 CPU 随手打分不合适，更适合 GPU / 批处理。
- 主要限制：它预测的是相对 helpfulness / preference，不是 toxicity 或 safety。模型卡明确提醒不要把它当伦理判断或毒性检测器。

单条回复打分的输入形态：

```text
POST: {prompt 或对话上下文}

RESPONSE A: {要打分的回复}

RESPONSE B: .

Which response is better? RESPONSE
```

## `OpenAssistant/reward-model-deberta-v3-large-v2`

来源：https://huggingface.co/OpenAssistant/reward-model-deberta-v3-large-v2

- 模型：DeBERTa-v3-large sequence classifier。
- HF task：text-classification。
- 训练数据：OpenAI WebGPT comparisons、OpenAI summarize-from-feedback、Dahoas synthetic instruction response pairs、Anthropic HH-RLHF。
- 模型卡报告 validation accuracy：
  - WebGPT：**61.57**
  - Summary：**71.47**
  - SyntheticGPT：**99.88**
  - Anthropic RLHF：**69.25**
- 打分方式：把 `(question, answer)` 作为 tokenizer 的 pair 输入，读取单个输出 logit 作为 reward score。一般 higher = 模型认为 answer 更好。
- 实际成本：`pytorch_model.bin` 约 **1.74GB**，明显小于 SteamSHP-XL，更适合作为我们先试的通用 scorer。
- 主要限制：这是英文偏好 reward model，不是校准过的通用 harm classifier。它可以做比较式排序，但安全评估里要保留审计。

最小打分代码形态：

```python
from transformers import AutoModelForSequenceClassification, AutoTokenizer

reward_name = "OpenAssistant/reward-model-deberta-v3-large-v2"
rank_model = AutoModelForSequenceClassification.from_pretrained(reward_name)
tokenizer = AutoTokenizer.from_pretrained(reward_name)

inputs = tokenizer(question, answer, return_tensors="pt")
score = rank_model(**inputs).logits[0].detach().cpu()
```

## 数据集关系

- `UltraChat`：论文 Section 7 里作为良性回复 baseline。原始 `openbmb/UltraChat` 已下载到 `data/UltraChat/openbmb__UltraChat/`。
- `HH-RLHF`：两个 reward model 的训练 / preference 来源之一，不是这篇 cognitive-overload 论文的攻击 benchmark。HF 数据集包含 helpfulness / harmlessness 的 chosen-rejected pair，以及单独的 red-team-attempts 子集。体量不大，下次可以直接下载：原始文件约 **79MB**，转换 parquet 约 **184MB**。
