# Manufacturing observations and exact joint-law analysis

Reproducible E1–E6 study of manufacturing semantics, observation-based model
identification, exact attainable probability bounds, target-preserving reduction,
transfer across Brandimarte Mk01–Mk10, and complete computational costs.

[Protocol](docs/PROTOCOL.md) · [Plan generation](docs/PLAN_GENERATION.md) · [Source provenance](provenance/sources.json)

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

The calibration models and independent production bank have been executed.
Descriptive validation analysis, external comparisons and final cost acceptance
are in progress. Primary releases and runs are listed in
[primary_runs.json](provenance/primary_runs.json); workflow success alone does not
establish complete experimental acceptance.

The separate plan generator searches assignments and operation order under
selectable nominal-duration, deadline-success, worst-regime and Pareto objectives.
It reports the best schedules found under the stated budget. Its new holdout is
separate from the already opened E1–E6 validation bank.
