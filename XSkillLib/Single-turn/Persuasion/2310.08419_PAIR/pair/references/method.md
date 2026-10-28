# Method Notes

PAIR stands for Prompt Automatic Iterative Refinement. It is a black-box,
prompt-level search algorithm. For each behavior, the attacker LLM proposes a
candidate prompt `P`, the target LLM responds with `R`, a judge scores
`JUDGE(P, R)`, and the tuple is appended to the attacker conversation history
when the attempt fails.

The paper runs several streams in parallel. Its default experiment uses 30
streams and 3 iterations, giving at most 90 target queries per behavior. The
attacker system prompts use three semantic strategies: roleplay, logical appeal,
and authority endorsement. The attacker output is constrained to JSON with
`improvement` and `prompt` fields so the refinement trace remains inspectable.

The official implementation is available at `.workspace/external/pair-2310.08419`.
It depends on JailbreakBench, LiteLLM, and FastChat. The local reproduction keeps
the PAIR algorithm in a single stdlib script and exposes simple fake/API
adapters.
