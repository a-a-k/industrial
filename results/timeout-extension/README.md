# Extended timeout repeats

[Report](REPORT_RU.md) · [Result](RESULT.json) · [Costs](costs.csv) · [Profile](profile.json)

These are unchanged outputs of
[Actions run 43726894373](https://github.com/a-a-k/industrial/actions/runs/43726894373).
The [complete evidence](https://github.com/a-a-k/industrial/releases/tag/timeout-supplement-43726894373-1)
retains both original and repeated process outcomes. Input logs were verified
byte for byte before new method executions. Both repeated cases completed all
warmups and five measured fresh processes per method without timeout or error.

The two timing pairs are comparable within their respective runner. The primary
300-second and repeated 1200-second results remain distinct. Runner hardware
also differed: the original R/full-projection job recorded AMD EPYC 7763, while
its repeat recorded Intel Xeon 6975P-C. Absolute times across these runs are not
a measurement of an implementation change. Both used a one-CPU cgroup quota.

The [RSS control](RESOURCE_NOTE_RU.md) confirmed that the recorded process-lifetime
peak can retain the launcher's pre-exec history. In these repeats the parent
verified a 343 MB input before spawning methods. Keep the raw RSS values, but
do not interpret them as an isolated memory peak of the algorithm or subtract
the parent's peak. The clean algorithm-only peak cannot be recovered from
these counters. Timing and exact-answer comparisons remain separately reported.
