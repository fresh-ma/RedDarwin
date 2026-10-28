# Method Notes

Evidence used:

- `digest/algorithms/alg-osg.tex`
- `digest/sections/03.01-defensive-measures-creation.md`
- `digest/sections/03.02-offensive-measures-generation.md`
- `digest/sections/03.03-indirect-jailbreak-attack.md`

Implemented components (all real LLM calls, paper-verbatim prompts):

- malicious content extraction from a source query (5-shot, Sec 3.1);
- defensive measure generation (2 guidelines + example, Sec 3.1);
- direct-correlation filtering (yes/no, Sec 3.2);
- offensive measure generation (Dr. Al template, Sec 3.2);
- final indirect prompt assembly + live target query (Sec 3.3);
- QSR + Following-Rate judge (Sec 4.4 rubric, verbatim).

Substitutions (documented, not omissions):

- attacker GPT-4 / GPT-4-Turbo / GPT-3.5 → OpenRouter `deepseek/deepseek-chat`
  (OpenAI-direct quota-dead; GPT routes 403 on this key);
- 3 human annotators → LLM judge with the verbatim Sec 4.4 rubric.
