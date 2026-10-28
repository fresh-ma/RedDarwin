# Defense Prompts

This directory contains the defense prompts used in our mitigation evaluation (Section VI).

## System-Prompt-Guard

**File:** `system_prompt_guard.txt`

A lightweight in-model defense that instructs the model to perform self-scrutiny prior to generation, explicitly directing attention to potential manipulation within the prefill. Set this as the system prompt before the conversation.

## Prompt-Detection Filter

**File:** `prompt_detection_filter.txt`

An LLM-based input filter that inspects the relationship between the user prompt and the prefill text to identify manipulation patterns. The detector uses majority voting across three independent LLMs and returns a binary SAFE/UNSAFE classification.
