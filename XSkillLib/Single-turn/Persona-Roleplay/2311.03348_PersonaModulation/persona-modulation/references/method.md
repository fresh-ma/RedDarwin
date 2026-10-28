# Method Reference

Paper: `2311.03348_persona-based-llm-jailbreak`

Public source:

- arXiv: `https://arxiv.org/abs/2311.03348`

The authors state that the exact prompt/dataset artifacts are intentionally
withheld for responsible disclosure. The paper still gives the reproducible
algorithm shape:

1. choose a harmful category;
2. define a misuse instruction;
3. define a persona likely to comply;
4. design a persona-modulation prompt;
5. query the target model and score the first response.

Local Code implements a deterministic renderer for steps 1-4 using the public
category table. It does not claim to recover the withheld GPT-4 assistant prompt
or exact private prompt set.

Missing/gated components:

- GPT-4 assistant generation of misuse instructions, personas, and prompts;
- real target-model completions;
- GPT-4 PICT judge calls;
- human-in-the-loop semi-automated prompt refinement.

Fidelity label: `partial_algorithm_code`.
