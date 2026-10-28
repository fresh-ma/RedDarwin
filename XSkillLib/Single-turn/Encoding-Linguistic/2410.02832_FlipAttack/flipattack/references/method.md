# Method Notes

FlipAttack transforms a raw harmful request before sending it to the target model. The implemented core is:

1. choose a flip mode;
2. transform the raw goal into a flipped string;
3. wrap it as a `TASK is ...` user message;
4. add a guidance prompt that tells the target how to recover the task before answering.

The script supports the four paper modes:

- `FWO`: reverse word order;
- `FCW`: reverse characters inside each word;
- `FCS`: reverse the whole sentence;
- `FMM`: use whole-sentence reversal but frame the recovery as word-order flipping.

The generator is deterministic and works on any CSV row containing `Goal`, `goal`, `Behavior`, `behavior`, `query`, `question`, or `request`.
