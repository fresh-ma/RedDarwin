---
name: cipherchat
description: "Reproduce CipherChat (2308.06463): encode a harmful request in a cipher (Caesar/Atbash/Morse/ASCII/Unicode) or keep it verbatim for SelfCipher, wrap it in the official cipher-expert system prompt with 3 enciphered unsafe demonstrations, query a black-box API target, rule-decode the response, and score it with a dual-metric LLM judge."
metadata:
  paper: "2308.06463_llm-cipher-jailbreak"
  method: CipherChat
  access: black_box
  attack_family: encoding-obfuscation
  ciphers: [selfcipher, caesar, atbash, morse, ascii, unicode, baseline]
  target_default: api:deepseek/deepseek-v4-flash
  judge_default: api:deepseek/deepseek-v4-flash
  judge_metrics: [asr_refusal_bypass, asr_content_harmful, asr_jailbreak_success]
  dataset: "official RobustNLP/CipherChat data_en_zh.dict, 11 CipherChat domains, EN+ZH (4378 rows)"
  script: scripts/attack.py
  status: evaluated
  result: "results/RESULT_2026-06-26.md — v4-flash audited asr_content_harmful 0.227 (34/150); SelfCipher ZH-Crimes 0.733 strongest"
---

# CipherChat (2308.06463)

## What
CipherChat is a black-box prompt jailbreak. It moves a harmful request out of natural
language into a cipher and wraps it in a system prompt that (1) assigns the model a
"cipher expert" role, (2) teaches the cipher, and (3) prepends three **enciphered
unsafe demonstrations** + the official toxic trailer. The model answers in the cipher;
the response is rule-decoded before judging. `SelfCipher` skips explicit encoding and
uses the "Cipher Code" role prompt + natural-language unsafe demos to evoke the model's
internal "secret cipher" — the paper's strongest, most portable variant.

This unit reuses the 2305.13860 reference harness (load -> apply transform -> async
OpenRouter target -> dual-metric LLM judge). Only the template-application step is
CipherChat-specific; cipher encode/decode is the official `encode_experts.py` verbatim,
and system prompts + demonstrations come from the official `prompts_and_demonstrations.py`
(bundled in `data/official_prompts_pack.json`).

## Use
- `scripts/attack.py render` — build enciphered prompt x dataset cases offline (inspect).
- `scripts/attack.py run` — query an `api:<model>` target and score with the dual-metric judge.
- `--ciphers` selects the parameter configs: `selfcipher,caesar,atbash,morse,ascii,unicode,baseline`.
- `--dataset` picks the official domain slice under `data/`.

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, dep `openai`). The API key is read from the global
`XSkillForge/.env` (`scripts/attack.py` walks up from the script dir to find the
nearest ancestor `.env`) — no per-skill `.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Run
```bash
cd XSkillLib/Single-turn/Encoding-Linguistic/2308.06463_CipherChat/cipherchat

# offline render (no network)
$PY scripts/attack.py render --ciphers selfcipher,caesar --limit-rows 2

# live run, config 1: Crimes domain, SelfCipher + Caesar, 10 rows each (20 cases)
$PY scripts/attack.py run \
  --ciphers selfcipher,caesar \
  --domain Crimes_And_Illegal_Activities \
  --limit-rows 10 \
  --target api:deepseek/deepseek-chat --judge api:deepseek/deepseek-chat \
  --out results/cipherchat_deepseek_crimes_selfcipher_caesar_10x2.json

# live run, config 2: Insult domain, ASCII + Atbash, 10 rows each (20 cases)
$PY scripts/attack.py run \
  --ciphers ascii,atbash \
  --domain Insult \
  --limit-rows 10 \
  --target api:deepseek/deepseek-chat --judge api:deepseek/deepseek-chat \
  --out results/cipherchat_deepseek_insult_ascii_atbash_10x2.json
```
`OPENROUTER_API_KEY` is read from the global `XSkillForge/.env` (walk-up search) or the environment.

## Test
- `render` must emit a system prompt containing the cipher role + `Example 0/1/2` demos
  + the toxic trailer, and a user turn that is the enciphered request.
- A live `run` must produce `summary.asr_refusal_bypass` and `summary.asr_content_harmful`
  computed from real per-case `verdict.refused` / `verdict.harmful` booleans, with
  `summary.ok == summary.cases` and `distinct_cipher_configs >= 2`.

## Settings
- Target / judge: any OpenRouter `api:<model>`. Default `deepseek/deepseek-chat` (fall
  back to `deepseek/deepseek-v4-flash` if it errors).
- Black-box only: `--target` must be `api:` (no GPU / local weights).
- `--max-tokens 1024 --temperature 0` (paper uses temperature 0).
- 3 enciphered unsafe demonstrations (official default), trailer verbatim.

## Recorded results
- `results/cipherchat_deepseek_crimes_selfcipher_caesar_10x2_20260624.json`
  — 20 cases, 2 ciphers, 20/20 ok. asr_refusal_bypass = asr_content_harmful = 0.65
  (SelfCipher 9/10 vs Caesar 4/10, matching the paper's SelfCipher > human-cipher finding).
- `results/cipherchat_deepseek_insult_ascii_atbash_10x2_20260624.json`
  — 20 cases, 2 ciphers, 20/20 ok. asr_refusal_bypass = 0.80, asr_content_harmful = 0.75
  (ASCII 9/10, Atbash 7 bypass / 6 harmful — the metrics diverge, confirming the judge
  is genuinely dual).

## Fidelity / divergence
Faithful: official ciphers (verbatim code), official system prompts, official 3 unsafe
demos + trailer, official EN dataset slices, decode-before-judge, temperature 0,
single-turn black box. Divergence: dual-metric OpenRouter LLM judge instead of the
paper's GPT-4 domain-specific toxic detector (`model_substitution_run`); target is an
open model (DeepSeek) instead of GPT-4/Turbo. Only EN Crimes + Insult domains are
bundled (the official dict has 13 EN domains x 199 items).
