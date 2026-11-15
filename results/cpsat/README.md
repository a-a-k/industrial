# CP-SAT schedules and independent validation

[Measured results](REPORT_RU.md) compare the original schedule, the frozen v1
heuristic and standard CP-SAT on a fresh paired holdout: 1024 whole-batch
scenarios per regime and instance. Nominal schedules were published before
the holdout. [Primary evidence](https://github.com/a-a-k/industrial/releases/tag/cpsat-report-43719097005-1).

| Instance | Operation schedule | Complete schedule and constraints | Nominal status |
|---|---|---|---|
| Mk01 | [CSV](schedules/Mk01.csv) | [JSON](schedules/Mk01.json) | OPTIMAL, 40 |
| Mk05 | [CSV](schedules/Mk05.csv) | [JSON](schedules/Mk05.json) | FEASIBLE, 173 |
| Mk10 | [CSV](schedules/Mk10.csv) | [JSON](schedules/Mk10.json) | FEASIBLE, 221 |

These are unchanged files exported on Actions from the frozen CP plans.
Machine indices start at zero. Times in schedule files are integer simulation
ticks: 100 ticks correspond to one original time unit. `nominal_makespan`
preserves the original reference C0; `planned_makespan` is the generated
failure-free duration. The same resources, original deadline and failure-law
scale are used for all plans.

Only Mk01 has a proved nominal optimum. None has a proved stochastic optimum.
The results establish improvement over the original plans on these synthetic
benchmarks, without claiming a new optimizer. The CP-seeded probability-search
interface is a separate version; its functional tests do not turn these
standalone CP holdout results into a validation of that new portfolio.
