# Mandatory short-CP control

During generation, before opening test outcomes, Mk05/1701 returned exactly the
same schedule from the 55-second CP stage, hybrid, CP-pool and long CP. Hybrid
spent 67.9 seconds and added no plan change. This known equality cannot establish
a benefit of local search. The two long-CP references alone are insufficient.

Extract the actual saved CP prefix from each of the nine immutable generation
releases. Do not repeat optimization. Freeze all four methods' schedules before
opening a new common `planner-prefix-holdout-v1`: 1024 replications per instance
and law, with complete DES/DAG and fixed 128-scenario original S1 checks.

The CP-short cost is an observed shared prefix, not a separately executed
standalone runtime. Attribute the recorded hybrid preparation window and the
nonnegative process-wall minus interface-wall overhead to CP-short. This
conservatively includes some preparation beyond CP and launch/finalization cost.
Report the CP-only observed wall and CPU separately. Never count the prefix free.

There are 54 fixed hybrid-versus-reference comparisons, including CP-short;
use alpha=0.05/216 for each one-sided binomial bound. Keep earlier experiments.
Do not choose a seed using any validation outcome.

The complete hybrid necessarily consumes more effort than its prefix. A better
probability therefore has an extra price, not an automatic claim of an equal-cost
improvement. Do not relax the earlier criterion after observing outputs. Exact
schedule equality establishes the same useful result from the cheaper prefix
without needing a statistical test. Any local-search probability difference
must be checked externally and reported with its added cost.
