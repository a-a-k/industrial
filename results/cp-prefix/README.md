# Four-method control with the actual CP prefix

[Report](REPORT_RU.md) · [Result](RESULT.json) · [All probabilities and costs](plans.csv)

These are unchanged outputs from
[Actions run 43734314101](https://github.com/a-a-k/industrial/actions/runs/43734314101).
The [full evidence](https://github.com/a-a-k/industrial/releases/tag/prefix-report-43734314101-1)
and [frozen schedules](https://github.com/a-a-k/industrial/releases/tag/prefix-seal-43734314101-1)
retain all variants. No optimizer was rerun for this control. All four methods'
plans were frozen before a new common holdout of 1024 scenarios per law and
instance; comparisons use the registered joint confidence family.

Local search returned its exact CP-prefix schedule in seven of nine conditions.
The other two changes did not produce a confirmed probability improvement over
the prefix. On Mk10, the long CP run had higher F1 success than hybrid in each
seed, while consuming more time. The local-search advantage is not established.

CP-short costs are observed common-prefix windows with explicitly attributed
overhead, not independently measured standalone runtimes. Whole-process RSS
also includes launch history, as shown by the [resource control](../timeout-extension/RESOURCE_NOTE_RU.md).

| Instance | Seed 1701 | Seed 1702 | Seed 1703 |
|---|---|---|---|
| Mk01 | [Schedules](schedules/Mk01/1701) | [Schedules](schedules/Mk01/1702) | [Schedules](schedules/Mk01/1703) |
| Mk05 | [Schedules](schedules/Mk05/1701) | [Schedules](schedules/Mk05/1702) | [Schedules](schedules/Mk05/1703) |
| Mk10 | [Schedules](schedules/Mk10/1701) | [Schedules](schedules/Mk10/1702) | [Schedules](schedules/Mk10/1703) |

Each folder contains CSV and JSON for `cp_nominal`, `cp_pool_mc`, `cp_short` and
`hybrid`. Machine indices start at zero. Times are integer ticks, 100 per original
time unit. `nominal_makespan` retains the original reference C0;
`planned_makespan` gives the generated duration. All seeds are retained rather
than choosing a winning seed using test outcomes.
