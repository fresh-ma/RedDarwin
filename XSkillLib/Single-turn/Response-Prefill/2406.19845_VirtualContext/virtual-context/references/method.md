# Method Reference

Paper core: create a virtual context by inserting a separator-like token in the
user input and placing an affirmative assistant-style suffix after it.

Implemented Code core:

- `plain` `<SEP>` style prompt;
- Vicuna/Llama2/Mixtral chat-template variants from the paper table;
- configurable confirmation suffix styles;
- optional OpenAI-compatible target adapter.

