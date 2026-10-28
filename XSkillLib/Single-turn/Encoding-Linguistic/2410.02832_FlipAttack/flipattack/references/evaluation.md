# Evaluation Notes

Durable live results should be written to:

```text
results/
```

The current script saves:

- the selected raw goal row;
- `model_input_messages`;
- joined `model_input_text`;
- raw `model_output_text`;
- a lightweight refusal proxy.

`fake` runs require `--wiring-check` and are only startup checks. They are not Code evidence. A paper-faithful ASR claim would require the paper's GPT-4-style judge and the full target/guard model set.
