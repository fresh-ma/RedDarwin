# Evaluation Notes

Default generation evidence is attack input only. The durable live gate records
the target model, generated offensive measures, model response, and named
verdicts using the shared safety-eval layout:

- `goal`: source harmful request.
- `completion`: target model output.
- `verdicts.refusal_bypass`: refusal-prefix bypass signal.
- `verdicts.qsr`: paper Query Success Rate rubric from Sec. 4.4.
- `verdicts.fr`: paper Following Rate rubric from Sec. 4.4.

The durable gate is
`../results/puzzler_clue_dsv4_combined40_20260625.json`: 40 completed target
calls (deepseek-v4-flash), 0 provider/runtime errors, raw QSR∧FR 0.70 (28/40) →
GLM-audited content_harmful 0.625 (25/40), refusal_bypass 1.00.
The judge is an OpenRouter LLM substitute for the paper's human panel; the
rubric itself is unchanged.
