# Method Notes

CodeChameleon turns a raw goal into a target-facing prompt in three deterministic steps:

1. encrypt the goal with a personalized rule;
2. insert the matching decryption function into a code-style task;
3. ask the model to complete the `ProblemSolver` workflow for the decrypted problem.

Implemented rules:

- `reverse`: reverse word order;
- `odd_even`: place odd-position words before even-position words;
- `length`: sort words by length while preserving original indices in JSON;
- `binary_tree`: encode words in an inorder-recoverable binary tree;
- `none`: ablation baseline.

The decryption code is not executed locally for the target. It is part of the prompt, matching the paper's code-comprehension scaffold.
