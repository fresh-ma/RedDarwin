# Compound Role-Playing

Paper-local reconstruction of the single-turn compound role-playing jailbreak
from arXiv:2604.02652. It composes an authoritative persona, a contrastive
good/bad table, and a JSON self-assessment request into one target-facing
message. Each element can be enabled independently for ablations.

```bash
# PY = /path/to/XSkillForge/.venv/bin/python (shared venv; key from global XSkillForge/.env)
$PY scripts/attack.py --render --sample 3
$PY scripts/attack.py --sample 20 \
  --target api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash
```

The retained full-combination run is `results/deakin_20260720_064807.json` with
20 completed target/judge cases, no errors, no truncations, and no empty target
outputs. The paper did not release its literal prompt or 70 evaluation prompts,
so this package is an explicit paper-grounded reconstruction rather than
byte-faithful official code.
