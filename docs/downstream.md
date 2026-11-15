# Private consumers and post-training

Arena owns measurement. A private research repository such as LLM-lab owns data
permissions, selection, SFT/DPO experiments and model artifacts.

A consumer should pin the Arena commit and schema version, validate the normalized
result, and retain the report's result hash alongside the frozen experiment.
Resolve trajectory and verifier-result hashes in its own private evidence store;
Arena deliberately carries no filesystem paths, credentials or download URLs.
The report itself is an aggregate; use the validated input for per-attempt joins.

Only independently verified, licensed, reviewed training-split material is eligible
for training. Check bytes against recorded hashes. A solved flag without available
verifier evidence or a trajectory is insufficient. Do not use development or final
test failures as training examples, including related repositories and derivatives.
Keep a fresh held-out evaluation bank outside the iterative data-generation loop.

A first experiment can compare unchanged and SFT-adapted students under matched
export/quantization and Arena protocols. Start with verified successes. DPO later
requires valid chosen/rejected continuations from comparable starting conditions;
a timeout, infrastructure error or verbose trace is not automatically a suitable
negative example. Train only assistant outputs, preserving tool-call structure;
do not train the model to invent tool observations. This repository implements
none of those training transformations.

There is no automatic public sync. Private users can run the public CLI offline,
retain private manifests and reports, and publish only separately reviewed results.
Review provider output permissions and task provenance before collecting training
material. No paid generation or compute is launched by Arena.
