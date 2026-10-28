# Plan — In-Context Attack (ICA), 2310.06387

## Paper
Wei, Wang, Wang. *Jailbreak and Guard Aligned Language Models With Only Few
In-Context Demonstrations* (2310.06387). Pure black-box prompt-prefix jailbreak.

## Attack mechanism (sec:3.2, alg:ica)
Prepend `k` harmful query+compliant-answer demonstrations `[x_1,y_1,...,x_k,y_k]`
before the target harmful request `x`. The final attack prompt is
`P_attack = [x_1,y_1,...,x_k,y_k, x]`, expressed as a multi-turn chat prefix
(demo queries as `user` turns, compliant answers as `assistant` turns), biasing
the victim toward the harmful sub-distribution `P_H`. Single forward pass; the
demonstration set is crafted once and reused across requests (universality).

## Depth
Faithful black-box reproduction of the ICA attack side. The official repo
`PKU-ML/adv-icl` is 404 (confirmed via `git ls-remote`), so the harmful
demonstration set `y_i` is reconstructed in the paper's documented appendix
style ("Sure, here's the first part of the tutorial ... Step 1 ..."). NOT
reproduced: GCG-on-surrogate demo crafting, the HarmBench LM judge + human
tie-break, the full multi-model target matrix, and 3-run averaging — these are
white-box / out-of-scope for a black-box unit.

## Target / judge
- Target: `api:deepseek/deepseek-chat` (OpenRouter, project default open model).
- Judge: `api:deepseek/deepseek-chat`, dual-metric (refusal-bypass +
  content-harmful), reused verbatim from the XSafeBench reference harness.

## Dataset route
AdvBench `harmful_behaviors.csv` (paper's own attack dataset, sec:5.1). The demo
set is drawn from the FRONT of AdvBench; the 20-row target slice is the LAST 20
behaviors, so target requests never overlap the demonstrations.

## Parameter configs (>=2 required)
Two shot counts: `ica_1shot` and `ica_3shot` (20 behaviors each = 40 cases).
Shot count is the paper's primary knob; ASR is expected to rise with more shots.

## Success criteria
>=10 cases, >=2 distinct configs, all cases return real dual-metric judge
verdicts (refused/harmful booleans) with computed `asr_refusal_bypass` and
`asr_content_harmful`. ASR magnitude itself is not a gate — deepseek-chat is
strongly aligned, and the paper shows low-shot ICA barely moves ASR on aligned
models (GPT-4 1-shot = 0%); the monotone 1-shot < 3-shot trend is the signal.
