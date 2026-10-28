# CodeAttack Runner

Black-box, single-turn code-completion jailbreak (arXiv 2403.07865). CodeAttack converts a
harmful natural-language goal into a code-completion prompt with three parts — input encoding
(e.g. the goal split word-by-word onto a Python stack), task decoding, and output-list
initialization — so the target model "completes the code" by filling `output_list` with the
harmful paragraphs. Prompt types: `python_string(_plus)`, `python_list(_plus)`,
`python_stack(_plus)` (default), `C_string`, `go_string`.

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + `python-dotenv`). API keys are read from the global
`XSkillForge/.env` (`scripts/codeattack_pkg/clients.py` walks up to find it) — no per-skill
`.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Quick checks (offline, no API calls)
```bash
cd XSkillLib/Single-turn/Code-Encapsulation/2403.07865_CodeAttack/codeattack
$PY scripts/attack.py --wiring-check --output /tmp/codeattack_wiring.json
$PY scripts/attack.py --render-only --n-requests 2 --output /tmp/codeattack_render.json
```

## Live run (target + policy judge over OpenRouter, key from global XSkillForge/.env)
```bash
cd XSkillLib/Single-turn/Code-Encapsulation/2403.07865_CodeAttack/codeattack
$PY scripts/attack.py --n-requests 10 --prompt-type python_stack_plus \
  --target api:deepseek/deepseek-v4-flash --judge policy \
  --judge-model api:deepseek/deepseek-v4-flash \
  --output results/codeattack_deepseek_probe.json
```

Default model-backed roles use `api:deepseek/deepseek-v4-flash`. `--judge none|rule|policy`:
`rule` is a refusal-substring heuristic, `policy` is the official 1-5 GPT-style rubric
(ASR = fraction scored ≥ `--judge-success-threshold`, default 5). `--wiring-check` uses
`mock:refusal` + rule judge (wiring-only, non-evidence).
