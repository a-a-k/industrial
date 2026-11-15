# Manufacturing observations and exact joint-law analysis

Reproducible E1–E6 study of manufacturing semantics, observation-based model
identification, exact attainable probability bounds, target-preserving reduction,
transfer across Brandimarte Mk01–Mk10, and complete computational costs.

[Protocol](docs/PROTOCOL.md) · [Plan generation](docs/PLAN_GENERATION.md) · [Source provenance](provenance/sources.json)

The current strong planning results and actual schedules are available in the
[CP-SAT report](results/cpsat/REPORT_RU.md) and
[schedule files](results/cpsat/README.md). On Mk10, the nominal duration is
375 → 221; a fresh independent holdout gives deadline success 19.04% → 84.57%
under F1 and 48.24% → 92.68% under F2, with the original deadline and machines.
This is a feasible plan from a standard solver, without a proof of optimality.

The experimental unit is one execution of a complete fixed batch. Production
observations and independent finished-product accounting are separate inputs.
Unknown outcomes at the observation horizon, missed production deadlines, and
computational timeouts have different meanings.

All builds, dependency resolution, tests, simulation, measurements and reports
run on standard GitHub-hosted Ubuntu runners. Workflows are dispatched explicitly.
The campaign has a zero monetary budget and a 72 runner-hour operational limit.
Complete evidence is published as versioned release assets; missing obligations
prevent a COMPLETE result.

The original S1 TSFG participant uses an unchanged private upstream kernel plus
the public operation adapter. Its source and binary are not distributed. DES and
DAG are independent open implementations and remain independently reproducible.

The calibration models, independent production bank and external comparisons
have been executed. Final cost acceptance is in progress. Primary releases and runs are listed in
[primary_runs.json](provenance/primary_runs.json); workflow success alone does not
establish complete experimental acceptance.

The separate plan generator searches assignments and operation order under
selectable nominal-duration, deadline-success, worst-regime and Pareto objectives.
It reports the best schedules found under the stated budget. The current
`industrial.plan` interface uses CP-SAT for the nominal objective and evaluates
original and CP-generated seeds under each requested probability objective
before further search. Its new holdout is
separate from the already opened E1–E6 validation bank.

[Frozen generated schedules](results/plans/README.md) provide the actual CSV and
JSON outputs, their units and links to independent validation evidence.

The earlier v1 independent plan-generation results are available in the
[Russian report](results/plan-generation/REPORT_RU.md),
[main comparisons](results/plan-generation/main-comparisons.json) and
[complete plan table](results/plan-generation/plans.csv). The report includes
simultaneous confidence bounds, all search costs and the limits of the claims.
