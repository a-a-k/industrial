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

The frozen v1 campaign uses the same standard multistart local-search implementation for all objectives:
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

The additional `nominal_best_frozen` reference is defined before opening holdout
results in `provenance/plan_reference.json`: the minimum nominal duration among
all frozen selected plans and the original schedule, with SHA256 ties. It uses
the same already tested plans, requires no additional simulations, and its cost
includes every generation run contributing to the set. Scalar nominal-search
incumbents are not the strongest nominal reference when a different frozen run
already found a shorter schedule. Different search trajectories and consumed
CPU prevent a claim of a pure causal objective effect at matched costs.


This block measures the practical effect of choosing an objective for a known
search method. It does not establish optimizer novelty or superiority over
stochastic scheduling literature. E1–E6 acceptance remains separate.

The current command selects CP-SAT for `nominal`. For `deadline_f1`, `worst_regime`
and `pareto`, CP-SAT receives one quarter of the complete budget, capped at sixty
seconds, then both its generated plan and the original inexpensive plan are
evaluated on the same calibration scenarios under the requested objective.
The direct-simulation search continues within the remaining budget. A nominally
shorter seed is not admitted as better without its requested probability score.
Input preparation and CP generation are charged to the same total budget.
The standard CP-SAT baseline
and its independent holdout are specified in [CPSAT_BASELINE.md](CPSAT_BASELINE.md).
The frozen v1 campaign and its output files remain unchanged. Execute on Actions:

```sh
python -m industrial.plan problem.json --folder output/generated \
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
The raw adapter supplies a deterministic condition hash as its dataset identity
and the existing five-tick discretization if omitted. Releases and processing
durations must be integer multiples of five. Benchmark generation and holdout
use the frozen `plan-generation-v1` tag; raw-interface verification runs
separately and does not alter those plans or their test bank.

For `--objective nominal`, use the isolated Python environment installed from
the hash-locked `cpsat-environment-43719097005-1` release. The output is
`schedule.json` with assignments, machine queues and start/end times, plus
`result.json` with the solver status and lower bound. `OPTIMAL` certifies the
nominal objective only; `FEASIBLE` reports the best solution found within the
budget. The other objectives retain `plan-XX.json` and the recorded empirical
search results. The callable entry point is `industrial.plan.generate`.

The [independent four-method control](../results/cp-prefix/REPORT_RU.md) did not
establish a quality/cost benefit of the added local search. In seven of nine
conditions its returned schedule exactly matched its CP prefix, with extra
expense; the other two changes had no confirmed probability gain over that
prefix. The probability-search branch remains experimental. Earlier standalone
CP improvements over the original schedules are not evidence for this branch.
