# Adversarial Tales consolidation plan

The paper's core mechanism is a one-shot narrative transformation, followed by
the same target model used for an untransformed baseline. The paper releases no
repository and withholds its 40 human-written tales, so this package is a
from-paper reconstruction rather than a source-derived implementation.

The local dataset is the exact N=20 historical AILuminate substitution sample;
it provides a self-contained replay surface but not paper-dataset parity. The
preserved N=10 and N=20 results remain valid historical model-substitution
evidence. A future API-only changed-algorithm run may run locally and must
record its target, transformer, judges, dataset provenance, and per-arm counts.
Request Deakin only if a future variant requires local weights or GPU work.
