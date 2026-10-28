# AdvBench Source

`harmful_behaviors.csv` was copied from the official `NJUNLP/ReNeLLM`
repository. This method-local copy is canonical and is the default dataset:

```text
assets/advbench/harmful_behaviors.csv
```

`scripts/attack.py` resolves `DEFAULT_GOALS` to this file (method-root relative).
