# Task-level and repeated-attempt metrics

Arena reports the complete matched matrix, with infrastructure-failed blocks
excluded for every contestant. Timeouts remain unsolved. A task/repetition block
is an attempt group, not another independent task. Model/tokenizer differences
also make raw token totals imperfect cost proxies.

## Equal task weights

The historical `matched_solve_rate` is attempt-weighted. When infrastructure
failures leave unequal repetitions per task, it can overweight tasks with more
remaining attempts. `matched_task_mean_solve_rate` instead averages each eligible
task's solved fraction with equal weight. `per_task` exposes the actual retained
and excluded repetition IDs and solved counts. `paired_task_differences` reports
per-task and mean differences on exactly the same matched tasks, without treating
repetitions as independent samples.

Neither is a confidence interval, a significance test or a promotion decision.
Related tasks can be correlated; a task count alone does not prove independent
project coverage. Source-disjoint confirmation and appropriate uncertainty remain
necessary for a broad quality claim. This follows the distinction between
repeated epochs and clustered observations in
[Inspect's metric guidance](https://inspect.aisi.org.uk/metrics.html).

## pass@k

For a task with n matched repetitions and c successes, Arena estimates success
within k samples using `1 - C(n-c,k)/C(n,k)`. The formula is the standard
[HumanEval estimator](https://github.com/openai/human-eval/blob/master/human_eval/evaluation.py),
independently implemented here with a bounded log-domain product and no NumPy or
vendored source. Exhaustive enumeration of sampled subsets checks its arithmetic.

Each k has an explicit shared task cohort: only tasks with at least k matched
repetitions are eligible for **every** contestant. The report lists those task IDs.
No eligible cohort yields `null`, not zero. Larger k can change the cohort; do not
read a sequence of these averages as a monotone curve over one fixed task set.
Timeouts count as failures; infrastructure exclusions do not become successes.

The estimator assumes exchangeable samples. A frozen seed schedule, deterministic
decoding or strongly correlated repeated attempts does not by itself establish
independent sampling. These values describe observed repeated-attempt coverage
under that assumption; they do not guarantee a deployable best-of-k selector,
cross-model ensemble performance or unseen-task generalization.

```sh
python3 -m keel_arena report "$PRIVATE_RESULT_FILE" --pass-k 1,2,4
python3 -m keel_arena report "$PRIVATE_RESULT_FILE" --pass-k 1,2 --format markdown
```

At most 16 distinct positive k values can be requested, each no larger than the
supported attempt-matrix limit. Reports are local stdout output and can contain
private task/model identifiers. The Markdown format preserves the purpose label,
coverage, unknown usage and task breakdown. It does not rank models or remove the
need for a separate publication review. JSON remains the default machine interface.
