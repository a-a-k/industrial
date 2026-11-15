# Industrial observations E1–E6, protocol 1.0

## Hypothesis and acceptance

The declared observation binding supports independently verifiable batch-success
semantics and identification of empirical compatible joint laws. Exact analysis
preserves attainable targets, contrasts and witnesses. The completion/deadline
reduction preserves R, while omitting structural information. The same procedure
is evaluated on Mk01–Mk10, with complete comparable computational costs.

External finished-product accounting supplies Y. Internal metrics alone do not
establish usefulness. Positive speedup or superiority over empirical frequency is
not required and must not be inferred from equivalence controls. Known equivalence
of full-R, projected-R and direct-R is an implementation invariant, not a new
algorithmic contribution. Results concern synthetic manufacturing observations.

The strongest simple baselines are streaming direct-R, direct-R combined with
structural queries using controls and aggregated completion, independent finite
enumeration, and calibration success frequency as a forecast comparator. All
identification methods receive the same primitive evidence and semantic contract.

## Observation and state semantics

One complete-batch replication is one attempt. The census retains every attempt,
including missing traces and unsuccessful production. The identifier receives
only contract, attempt journal and permitted operation records. External Y,
mission_success, expected_success and hidden calendars are not inputs.

Every technological operation remains a graph node. X[o,m] is sound evidence of
receipt of that operation at machine m inside its contract window. D[o,m] records
actual selection among declared compatible machines. Missing/conflicting evidence
is unknown. One C[j] per job represents its mandatory local postconditions;
C_dispatch represents local dispatcher acceptance, never external batch success.
An initially failed machine may receive work after repair; interruptions do not
erase established delivery. Reassignment is unsupported in version 1.
The receipt window ends at the earlier of observed attempt completion and H;
changing an evaluation deadline changes T only, not the X/D/C observation binding.
Records after H do not establish observed coordinates. Explicit final delivery
rejection may establish X=0; absent or contradictory evidence remains unknown.

The observation horizon is H=1.25*C0. Process all events at H before stopping.
Confirmed local postcondition gives C[j]=1, explicit terminal failure gives 0,
and an unresolved outcome gives unknown. An attempt not completed by deadline d
has T[d]=0. Completion times after H remain unknown. Deadlines only score the
execution; they do not cancel work. A computational timeout is not T[d]=0.

В основных расчётах сохранять декартово множество состояний, совместимых с
известными координатами наблюдения. Дополнительные физические ограничения
проверять в отдельно обозначенном опыте E3.

Do not impose one-hot choices, technological implications, or completion-implied
eligibility on unknown coordinates in the main compatible-state family.
The model root is a dispatcher with one unguarded replica and no selection;
all mandatory operations are required targets. Optional work is not a target.

## E1–E4 qualification

E1: success, queue lateness, initial failure then recovery, suspend/resume,
failed local quality postcondition, missing record, unexplained mandatory link,
optional work, reassignment, unresolved H outcomes and events exactly at H.
Require exact expected values, unknowns and support/refusal statuses.

E2: hand-calculated structure, attempts, masks and integer joint counts; record
permutation, whole-trace loss, conflicting completion, missing operation and
unsupported causal boundary. Test equal-marginal completion and selection laws.
Separately discover a fixed six-node graph from independently registered edges:
p in {0,.01,.1,.5,1}, n in {16,64,256,1024}, 256 independent sequences per p.
Compare missing-edge proportions to (1-p)^n; short sequences need not recover all
edges. Never invent p=0 edges. Rebind all records against the final discovered
schema. E5 does not learn its graph from its statistical samples.

E3: retain the published 128-state/2187-observation regression; independently
enumerate complete states without importing tested predicates or solvers. Check
joint attainable target vectors, scalar bounds, same-state contrasts and complete
endpoint witnesses. Add 65 coordinates with eight unknowns (256 compatible states),
more than ten controls, and maximum manufacturing-schema feasibility. For each
category CUDD minimizes/maximizes the restricted Boolean target and aggregates
with exact count/n weights. Verify full witnesses for both endpoints, including
singletons. Verify vector images by joint root intersections. The physical
C2<=C1 restriction and C1*(1-C2) negative control are separate families/queries.

E4: the 20 equally weighted elementary scenarios have rows
(count,T,C1,C2,K)=(6,1,1,1,1),(4,1,1,?,1),(3,0,?,?,?),
(2,1,0,?,?),(3,1,1,1,?),(2,1,1,?,?). Exact answers:
I(R)=[.45,.75], I(E)=[.30,.75], I(R-E)=[0,.25]. Full-R,
projected-R and direct-R agree, with reduced category masses 9,6,3,2.
Reveal K=1, then reveal three of six unknown C2 as true, obtaining R=.60.
Test information refinement on production observations as well.

## E5 production and prediction

Freeze one list_v1 schedule for each Mk01–Mk10. C0 is its failure-free makespan.
Use deadlines C0,1.10*C0,1.25*C0; primary deadline 1.10*C0; H=1.25*C0.
Use 512 calibration and 1024 independent validation replications for each of
10 instances and two laws: 30,720 stochastic scenarios, plus ten nominal controls.
DES and independent DAG run the complete bank. Original S1 TSFG runs all nominal
and E1 production controls plus a preselected 128 validation scenarios per
condition (2,560 stochastic scenarios). Require exact operation starts, finishes,
remaining work and deadline/identification agreement on completed paired runs.

F1: initially all machines up. Up times and repairs are exponential with means
2*C0 and .1*C0 before rounding. Successive cycles and machines are independent.
Round each strictly positive duration upward to the adapter grid (5 ticks;
100 ticks per original instance time unit). F2: independently per replication,
a fair coin chooses one shared calendar for all machines or independent calendars
with the same component law. Save the pre-rounded law and discretization metadata.
Generate calendars first and give engines identical histories, not just seeds.

Freeze bindings/algorithms before opening Mk08–Mk10 for the new procedure;
disclose prior use in the legacy TSFG study. Seal calibration predictions before
validation acquisition/outcomes. Report F1->F1, frozen F1->F2 and refitted F2->F2.
Observation modes: all available records, nested independent deletion .1/.3,
informative deletion (.1 after Y=1, .5 after Y=0), whole-trace loss .1.
The masker may access Y; the identifier cannot. Unobserved unused-replica X values
remain unknown even in the all-available-records mode.

For probability bounds count attempts with guaranteed success k_minus and
possible success k_plus. The outer 95% region uses a one-sided 97.5% lower
Clopper–Pearson bound for k_minus/n and one-sided 97.5% upper bound for k_plus/n.
Test Y frequency has its own 95% binomial interval. For a separate 95% discrepancy
region use four one-sided 98.75% bounds: lower calibration-guaranteed, upper
calibration-possible, lower and upper validation success. Subtract as
[L_cal-U_test,U_cal-L_test]. Apply these constructions only to binary per-attempt
extrema and counts, not arbitrary real optimization outputs. Confidence is per
condition, not simultaneous across all tables. Three deadlines do not triple n.
Report point signed/absolute error, interval width, empirical error range and
distance to validation frequency, with sampling uncertainty. Do not replace an
interval by its midpoint or require superiority over calibration frequency.

## E6 costs and execution

Measure trajectory production, parsing/binding, model construction/storage,
single-R query, full target panel, repeated saved-model analysis and certificates.
Use the specialized query_full_r for full-R. The combination baseline retains
controls and the completion conjunction rather than all individual completions.
Repeated-log sizes 1000/10000/100000 are computational loads, not larger samples.
The independent small-model cost control uses the existing seven-coordinate E3
fixture with all 2187 partial categories, each of weight one. Full CUDD and the
independent exhaustive scalar evaluator produce the same thirteen scalar bounds;
neither timed path computes joint images or witnesses. Freeze the saved model and
its SHA256 before one warmup and five measured fresh processes per method. This
control supplements the forty industrial cost cases and closes the original
small-model timing obligation without adding production replications.

Pair methods sequentially on the same standard Ubuntu runner, one CPU, 4 GiB.
CPython 3.11.16 and the dd 0.6.0 cp311 CUDD wheel are pinned. Resolve/hash the full
environment on Actions before qualification and measurements. One warmup plus
five measured fresh processes per method; reproducibly permute method order.
Warmup counts toward campaign cost, not the five-run timing statistic. Repeated
saved-model queries occur separately within a process. Include preparation,
serialization, failures and certificate costs in the relevant total. Record wall,
CPU, peak RSS, representation size and completion fraction. Preserve timeouts as
censored durations, never completed values.

Zero monetary budget: public repository and standard ubuntu-24.04 runners only;
no larger runners, paid storage, LFS, Packages or Actions cache. Publish evidence
directly to Releases, each file <2 GiB and <=1000 assets per release; spill to a
new numbered release before either limit. Do not use Actions artifact storage.
Per compute subprocess limit 300 seconds; job limit 90 minutes; at most four
concurrent jobs. Total operational budget 72 runner-hours includes preparation,
warmups, failed runs, reports and verification. Reserve job time before dispatch.

An isolated identification job gets only permitted inputs and implementation;
changing all external Y labels must leave models/results unchanged. Compare
saved results in fresh processes. Required qualification failures block affected
production stages. All obligations have explicit completed/failed/timeout/unrun
statuses. Exhausted budget or missing required evidence means PARTIAL. Neither a
pilot nor direct-R substitutes for full-model obligations. Final claims require
independent rechecking against this original criterion.

Core qualification is distinct from complete block acceptance. Maximum-schema
feasibility follows the frozen core qualification. The first required Mk01-F1
calibration bank then supplies E4 masking/refinement and isolated-identification
acceptance before the remaining calibration conditions are opened. It counts
once toward the required bank and is not an additional pilot or substitute series.
