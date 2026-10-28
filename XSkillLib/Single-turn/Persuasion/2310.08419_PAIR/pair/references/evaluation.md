# Evaluation Notes

The paper evaluates on JailbreakBench behaviors and reports jailbreak
percentage plus queries per success. It uses Llama Guard with the
JailbreakBench prompt as the primary judge and compares against GCG and human
jailbreakchat templates.

JailbreakBench later released PAIR artifacts under
`.workspace/external/jbb-artifacts/attack-artifacts/PAIR`. Those artifacts are
useful for checking published prompt/response result shape, but they are not a
replacement for reproducing the PAIR search algorithm.

The local fake/proxy path is only a `wiring_check` startup and format check. A
live reproduction should specify an attacker model, a target model, and either
JailbreakBench/Llama Guard or a clearly labeled content-aware judge.
