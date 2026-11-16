# Manufacturing crash tests and plan generation

The primary engineering task is to crash-test a fixed technologist-approved
plan, explain weak places, and validate targeted corrections. The
[fixed-plan diagnostic protocol](docs/FIXED_PLAN_DIAGNOSTICS_RU.md) separates
observed delays, causal sensitivity and feasible local changes. Archived Mk10
is a research example; causal benefits of corrections are not yet established.
The [first diagnostic report](results/fixed-plan-diagnostics/REPORT_RU.md)
contains the unchanged plan's observed waits, affected operations and an example
waiting chain. It does not select a replacement schedule.

The [full local-reinforcement protocol](docs/FIXED_PLAN_REINFORCEMENT_RU.md)
covers all ten fixed nominal plans under F1/F2, one feasible local correction,
strong open controls and a common decision seal before independent validation.
Detailed reports include the physical operation/machine edit, complete schedule
files and external whole-batch effects. Commercial products are not measured.

The [manufacturing report](results/objectives/REPORT_RU.md) presents whole-batch
deadline risk under machine failures, schedules generated from raw conditions,
external checks of each objective and complete search costs. The
[plan catalog](results/objectives/catalog.csv) links actual JSON and CSV schedules
for nominal duration, deadline success, worst-regime success and Pareto objectives,
with historical and current versions kept separate.

Reproducible E1–E6 study of manufacturing semantics, observation-based model
identification, exact attainable probability bounds, target-preserving reduction,
transfer across Brandimarte Mk01–Mk10, and complete computational costs.

Virtual execution under sampled failures is part of the method being evaluated.
The [scope of the results](docs/RESULT_SCOPE_RU.md) distinguishes these crash tests
from subsequent observation analysis and the separate plan optimizers. E6 times
analysis of already generated observations; it does not measure the complete
crash-test pipeline against direct Monte Carlo.

The additional [complete input-to-risk comparison](results/end-to-end/REPORT_RU.md)
has now finished: 648 of 648 processes completed, with no failures or timeouts.
It includes preparation, freshly generated failure histories, virtual execution,
the risk estimate and confidence interval. In all 36 condition/runner pairs,
the existing S1/SIMPAT implementation returned the same answer at higher elapsed
cost than indexed DAG/direct Monte Carlo, including first-use preparation.
This is a negative comparative result for the declared fixed-queue task. The
shared-DAG/SIMPAT control separates representation cost from S1 execution cost.

The [implementation audit](results/implementation-audit/AUDIT_RU.md) reproduced
and fixed input-boundary defects; all 40 qualification tests passed in
[GitHub Actions](https://github.com/a-a-k/industrial/actions/runs/43742757573).
Its phase checks explain why projection after full construction took almost the
same time as full construction. A separate paired measurement of direct reduced
construction took 107.74 s versus 240.78 s for full construction, with the same R
interval. This is a postprocessing comparison, not a complete-pipeline speedup.

[Protocol](docs/PROTOCOL.md) · [Plan generation](docs/PLAN_GENERATION.md) · [Source provenance](provenance/sources.json)

The [three-method comparison protocol](docs/PLANNER_COMPARISON.md) defines a
separate equal-budget test of CP-SAT, CP incumbent ranking by direct simulation,
and CP-seeded local probability search. The completed
[three-method report](results/planner-comparison/REPORT_RU.md) and
[mandatory short-CP control](results/cp-prefix/REPORT_RU.md) do not establish a
benefit of additional local search. It returned its exact CP-prefix schedule in
seven of nine conditions; the two changed schedules showed no confirmed gain
over that prefix. All plans and seeds are retained with complete costs.

The standalone CP-SAT validation and actual schedules are available in the
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

The [E1–E6 report](results/industrial/REPORT_RU.md) records E1–E5 PASS and
E6 PARTIAL. All 30,720 production scenarios and all 492 scheduled cost attempts
were executed. Thirty-nine of 41 paired cost cases completed; two cases have
computational timeouts. Primary releases and runs are listed in
[primary_runs.json](provenance/primary_runs.json); workflow success alone does not
establish complete experimental acceptance.

The two censored cases have also been completed in a
[separate timeout supplement](results/timeout-extension/REPORT_RU.md): all 24
repeat processes returned answers under a 1200-second limit. Full outputs are
therefore available for 41 of 41 cases under two explicitly recorded limits.
The original 300-second series and its PARTIAL status remain unchanged.

At the primary deadline, estimates from the initial simulated batch and frequencies
in the independent validation batch have descriptive mean absolute differences
across ten instances of 2.43 percentage points under F1 and 1.75 under F2.
Both batches use the declared failure law; these are synthetic executions, not
factory history. Applying the F1 estimate to F2 executions gives a 20.71-point
mean difference. This does not test a forward calculation supplied with the
correct F2 law. With no artificial deletion of records, subsequent identification
reproduces the initial simulated batch's frequency exactly; sparse records can
yield broad identification intervals. These checks establish neither real-factory
prediction accuracy nor an advantage over direct Monte Carlo.

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
