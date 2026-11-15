# Generation under selectable objectives

Generate machine assignments and operation order from the same operations,
compatible alternatives, release times and precedence constraints. Resources,
processing requirements and deadline remain fixed. The existing `list_v1` plan
supplies the initial schedule and the fixed reference C0, not a closed set of
candidate schedules.

The objectives are `nominal` (minimum failure-free makespan), `deadline_f1`
(maximum probability of batch completion by the fixed deadline under F1),
`worst_regime` (maximum minimum empirical success probability over F1/F2) and
`pareto` (nondominated failure-free duration and the two regime probabilities).
These are best-found schedules under a finite search budget. Global optimality
and a complete Pareto front are not claimed.

Use the same standard multistart local-search implementation for all objectives:
change one compatible assignment or swap operation priorities; a serial feasible
decoder enforces predecessors, releases and single-machine capacity. Restart
after 32 unsuccessful moves. Preserve the initial incumbent. Common calibration
calendars use the original C0 and the already defined F1/F2 laws. Direct Monte
Carlo success frequency is the evaluator: full-model R is mathematically equal
under complete observations and is not an independently superior optimizer.

The fixed campaign in `provenance/plan_generation.json` covers Mk01/Mk05/Mk10,
four objectives and three search seeds. Each run gets the same upper bound of
240 seconds including input and calendar preparation, and 1000 candidate
evaluations. Report actual consumed time and the stopping reason, including
early evaluation limits, preparation, failures and cache hits. Different
objectives can consume different fractions of this upper budget. Preserve
candidate encodings and empirical outcomes, not only the winning fitness.
Pass the remaining wall time into every native candidate evaluation, stop an
incomplete evaluation without admitting its score, and preserve the previous
incumbent. Reserve five seconds for finalization. A complete child process that
exceeds 240 seconds is explicitly marked BUDGET_EXCEEDED rather than accepted.

For Pareto output, retain coordinate extremes, then deterministic farthest
points after normalization by observed coordinate ranges; cap the internal
archive at 128 and the reported subset at nine. Archive truncation and finite
sampling limit the search. Before final output, recompute nondominance against
all evaluated cached points, so truncation cannot leave a known dominated plan
in the reported subset. Nominal ties break by duration for deadline F1; worst
regime ties break by average empirical probability and then duration.

Freeze all generated plans before producing the new shared 1024-replication
holdout for each regime. Reusing the already opened E1–E6 validation as a new
independent test is prohibited. Compare external whole-batch completion against
the original list_v1 plan and the nominal-objective plan from the corresponding
seed. DES/DAG transitions remain independent; original S1 TSFG checks the fixed
128-scenario subset. Success at d needs no execution beyond d. Report generated
plan feasibility, per-regime success counts, paired changes, uncertainty, all
costs, failures and unknown results separately. Confidence is per comparison;
reusing scenarios across plans does not increase the number of replications.

This block measures the practical effect of choosing an objective for a known
search method. It does not establish optimizer novelty or superiority over
stochastic scheduling literature. E1–E6 acceptance remains separate.

The callable interface is `planning.generator.search(data, objective, evaluator,
identity, budget_s, seed)`. For the pinned direct simulator, execute on Actions:

```sh
python -m industrial.plan_campaign search problem.json --folder output/generated \
  --objective worst_regime --seed 1701
```

`problem.json` contains `conditions` (machine count, jobs and operations with
compatible machine/work alternatives, predecessors and releases), `deadline` in
the same integer ticks, and `spec` following `provenance/plan_generation.json`.
No starting schedule is required: list_v1 constructs it from the conditions and
its cost is included in preparation. Alternatively `dataset` can supply a
previously frozen starting schedule, as in the benchmark campaign. The starting
schedule defines the fixed reference scale. Search produces new assignments and queues. The instance must
use the supported fixed-assignment, suspend/resume execution contract; arbitrary
new production rules require a separate validated adapter.
An injected evaluator accepts `(plan, objective, remaining_s)` and must raise
`planning.generator.BudgetStop` instead of returning an incomplete score.
