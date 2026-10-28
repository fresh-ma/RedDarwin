# TAP Runner

Tree of Attacks with Pruning (TAP, arXiv:2312.02119): an attacker LLM iteratively
refines jailbreak prompts in a tree search (branching → pruning by on-topic +
judge scores) against a black-box target, with an evaluator LLM scoring responses.

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + `python-dotenv`). API keys are read from the global
`XSkillForge/.env` (`scripts/tap_pkg/clients.py: load_method_env` walks up ancestor
directories to find it) — no per-skill `.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

Use from the method root:

```bash
cd XSkillLib/Single-turn/Persuasion/2312.02119_TAP/tap
$PY scripts/attack.py --help
```

Smoke (offline, no API calls):

```bash
$PY scripts/attack.py --render-only --n-requests 2 --output results/render_probe.json
$PY scripts/attack.py --wiring-check --output results/wiring_check.json
$PY scripts/attack.py --target mock:empty --attacker mock:tap_attacker --evaluator mock:tap_evaluator --n-requests 1 --branching-factor 1 --width 1 --depth 1 --max-attack-attempts 1 --model-call-retries 2 --retry-sleep 0 --output results/empty_target_probe.json
```

Model roles are independent:

- `--attacker`
- `--target`
- `--evaluator`

All default to `api:deepseek/deepseek-v4-flash` (routed over OpenRouter, key from the
global `XSkillForge/.env`).
