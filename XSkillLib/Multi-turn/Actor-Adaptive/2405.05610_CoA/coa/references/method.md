# Method Notes

CoA is a contextual multi-turn attack. The reproduced loop is:

1. generate a seed chain of prompts whose semantic relation to the target objective increases by round;
2. execute the chain against the target model with conversation history;
3. compute a semantic progress score for each target response;
4. choose a walk action:
   - `next_walk` when semantic relevance increases;
   - `regen_walk` when the current prompt should be regenerated;
   - `back_walk` when progress regresses;
   - `end_walk` when the judge marks success.

This code-simplified version keeps the state machine and model-feedback updater visible in one file.
