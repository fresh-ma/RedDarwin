# Evaluation Reference

The paper reports harmful completion rate over 43 categories:

- 1 misuse instruction per category;
- 5 personas per instruction;
- 3 persona-modulation prompts per persona;
- 3 completions per prompt;
- 45 completions per category, 1,935 completions per target model.

The paper scores only the target model's first response after the misuse
instruction. It uses GPT-4 as a zero-shot PICT classifier and validates it
against 300 human labels, reporting high precision but lower recall.

Local Code currently:

- generates target-facing persona-modulated prompts;
- can call an optional OpenAI-compatible target;
- can prepare PICT judge prompts for saved completions.

Local Code does not run the GPT-4 PICT judge by default. Any live target output
without PICT or human judgment is only a probe, not paper-faithful harmful
completion rate.
