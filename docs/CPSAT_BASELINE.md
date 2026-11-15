# Strong nominal planning baseline

The first heuristic experiment improved the original list schedule, but its
nominal results do not establish strong optimization quality. The same pinned
instance source lists optimum 40 for Mk01 and known upper bounds 172/197 for
Mk05/Mk10. These are published reference metadata, not measurements of this code.

Use the standard OR-Tools CP-SAT flexible-job-shop model as an additional actual
generator: exactly one compatible machine per operation, technological
precedence and nonoverlapping machine intervals. One CPU, 4 GiB, seed 1701,
240 seconds including model construction and result storage, one run per
Mk01/Mk05/Mk10. The original inexpensive schedule is a feasible hint; the prior
expensive heuristic result is not given as a free hint. Report solver status,
incumbent, lower bound and complete consumed time. FEASIBLE is not OPTIMAL.

Normalize time units by the gcd of the given durations and releases. For the
nominal problem, earliest schedules on a fixed assignment/order have starts on
this grid, so an optimal nominal schedule is retained. Decode the selected
assignments and machine order to earliest feasible starts. Both operations are
standard equivalent transformations, not new optimizer contributions.

Keep OR-Tools and its frozen wheels in a separate virtual environment. The
original CUDD/statistics environment and qualified scientific modules remain
unchanged. Compare the small CP model with exhaustive assignment/order results;
independently verify nominal execution using DES, DAG and original S1.

Publish all three resulting plans before drawing a new common holdout
`cpsat-holdout-v1`: 1024 scenarios per instance and law F1/F2. Compare only the
CP plan, the original plan and the previous best frozen heuristic plan; there
is no need to repeat all 45 previous candidates. Retain original C0 for deadlines
and failure laws. Verify DES/DAG on all scenarios and S1 on 128 fixed scenarios.
The twelve CP-versus-reference comparisons use 48 one-sided binomial bounds at
alpha=0.05/48 for joint coverage at least 95%. More nominal speed does not by
itself imply more reliability; only the fresh outcomes establish that result.

Sources: [official model](https://github.com/google/or-tools/blob/stable/examples/python/flexible_job_shop_sat.py),
[pinned instance metadata](https://raw.githubusercontent.com/SchedulingLab/fjsp-instances/f960b0b75b132488ddba9ec17a3b1ce77ab751db/instances.json).
