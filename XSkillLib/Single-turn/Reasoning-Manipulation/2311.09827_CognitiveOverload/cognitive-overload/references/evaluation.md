# Cognitive Overload Evaluation Notes

The paper reports ASR by checking whether target responses contain rejection
phrases; non-English responses are back-translated to English using
NLLB-200-distilled-1.3B before phrase matching.

Current Code evidence is `generated_attack_input`: no target model output and no
ASR are produced in the local render run.

Paper-faithful live evaluation would require:

- target LLM calls for the selected model family;
- NLLB back-translation for non-English responses;
- rejection-phrase ASR computation;
- additional Mistral/DPR stages for veiled expression and effect-to-cause modes.
