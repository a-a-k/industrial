# Frozen generated schedules

These files are unchanged outputs of the GitHub Actions validation campaign.
They are selected by the minimum nominal-duration rule in
[`plan_reference.json`](../../provenance/plan_reference.json).

| Instance | Operation schedule | Complete input and schedule | Source release |
|---|---|---|---|
| Mk01 | [CSV](Mk01.csv) | [JSON](Mk01.json) | [Evidence](https://github.com/a-a-k/industrial/releases/tag/plan-validation-Mk01-43708009776-1) |
| Mk05 | [CSV](Mk05.csv) | [JSON](Mk05.json) | [Evidence](https://github.com/a-a-k/industrial/releases/tag/plan-validation-Mk05-43708009776-1) |
| Mk10 | [CSV](Mk10.csv) | [JSON](Mk10.json) | [Evidence](https://github.com/a-a-k/industrial/releases/tag/plan-validation-Mk10-43708009776-1) |

Times are integer simulation ticks: 100 ticks correspond to one original time
unit. `planned_start` and `planned_end` describe failure-free execution;
machines and precedence remain fixed during a failure scenario. The JSON field
`nominal_makespan` preserves the original reference C0 for the common deadline
and failure-law normalization; `planned_makespan` is the generated schedule's
failure-free duration. These schedules are best found under the declared search
budget, without a global optimality guarantee.
