# Prefill-Level Jailbreak Attacks on Large Language Models

A framework for evaluating prefill-level jailbreak attacks against safety-aligned LLMs. This repository implements 7 attack categories and 2 generation strategies (static template + adaptive) as described in our paper.

## Demo

[![asciicast](https://asciinema.org/a/tPZoDQ9nekPGoCjN.svg)](https://asciinema.org/a/tPZoDQ9nekPGoCjN)

## Attack Categories

| Category | Description |
|---|---|
| Scenario Forgery | Constructs fictional contexts to legitimize harmful requests |
| Persona Adoption | Forces the model to adopt roles that disregard safety rules |
| Intent Hijacking | Distorts, redefines, or fabricates user intent |
| Commitment Forcing | Skips safety decisions by pre-establishing compliance state |
| Continuation Enforcement | Provides harmful answer beginnings exploiting autoregressive completion |
| Structured Output | Forces specific output formats that prioritize structure over content filtering |
| Refusal Bypass | Mimics model refusals then uses transitions to break logical chains |

## Generation Strategies

- **Static Template**: Fixed, pre-designed prefill templates for each attack category
- **Adaptive**: Feedback-driven iterative optimization using an attacker LLM (up to 10 iterations)

## Evaluation

Two complementary Attack Success Rate (ASR) metrics:

- **String Match (SM)**: Checks model output against predefined refusal keywords
- **Model Judge (MJ)**: Multi-model majority voting using three independent LLM judges (e.g., gemini-2.5-pro, gpt-4o, claude-sonnet-4). Each judge uses **function calling** for structured output when the provider supports it, with text-based fallback. A response is classified as a successful jailbreak only if at least 2 of 3 judges agree.

## Project Structure

```
├── main.py                  # Experiment entry point
├── configs/
│   └── default.yaml         # Experiment configuration
├── core/
│   ├── attacks/             # 7 attack implementations + synergy wrappers
│   ├── models/              # LLM provider interfaces (DeepSeek, Gemini, OpenAI, Anthropic, OpenRouter, Aliyun)
│   ├── evaluators/          # String match, single model judge & majority vote judge
│   └── utils/               # Dataset, config, logging utilities
├── defenses/                # Defense prompts (System-Prompt-Guard & Prompt-Detection filter)
├── scripts/
│   └── verify_prefill_support.py  # Verify prefill support for any model
└── dataset/
    └── advbench.txt         # AdvBench harmful behaviors (520 prompts)
```

## Quick Start

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure API keys in `configs/default.yaml`:
   - Set victim model API keys
   - Set attacker model API key (for adaptive attacks)
   - Set judge model API keys (for model judge evaluation)

3. Run experiments:
```bash
# Run with default config (adaptive attacks, majority vote judge)
python main.py --config configs/default.yaml
```

## Configuration

Edit `configs/default.yaml` to customize:

- `victim_models`: Target models to attack (supports multiple providers)
- `attacker_model`: LLM used for adaptive attack generation
- `judge_models`: List of LLM judges for majority vote evaluation
- `attack_config.attack_methods`: Which attack categories to run
- `attack_config.generation_method`: `"static"` or `"adaptive"`
- `attack_config.max_iterations`: Max iterations for adaptive attacks (default: 10)

The framework also supports a single `judge_model` for backward compatibility.

## Supported Providers

| Provider | Prefill Mechanism | Config Key |
|---|---|---|
| DeepSeek | `prefix=True` on assistant message | `deepseek` |
| Google Gemini | OpenAI-compatible interface | `gemini` |
| OpenAI | Legacy models (GPT-3.5/4-0314) only | `openai` |
| Anthropic | Native Claude API with prefill | `anthropic` |
| OpenRouter | Multiple upstream providers | `openrouter` |
| Aliyun DashScope | `partial=True` on assistant message | `aliyun` |

## Prefill Support Verification

To verify whether a model supports prefill before running attacks:

```bash
python scripts/verify_prefill_support.py \
    --provider openrouter \
    --model meta-llama/llama-4-scout \
    --api-key YOUR_KEY \
    --output verification_log.json
```

## Citation

If you use this code, please cite our paper.
