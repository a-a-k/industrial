# Probability-search comparison at a fixed computational budget

The primary user objective is maximum probability of completing the whole batch
by the original deadline on the same machines. Test whether CP-seeded local
search produces a better external result at no greater actual effort than
strong simple alternatives. A known equivalent probability calculation is not
an optimizer contribution.

For each Mk01/Mk05/Mk10 and seeds 1701/1702/1703, run three methods on one runner,
one CPU and 4 GiB, in deterministically shuffled order. Each receives the same
conditions, failure-law specification and F1 calibration bank of 64 scenarios,
with a complete 240-second upper budget including preparation and saving:

- `cp_nominal`: standard CP-SAT minimizing nominal duration. Failure information
  is available but does not enter its nominal objective.
- `cp_pool_mc`: collect up to 256 intermediate CP incumbents within 200 seconds,
  then directly rank candidates using the same calibration success criterion.
  Evaluate the original and final nominal incumbent first; remove duplicates
  by actual machine assignment and order. Unfinished evaluations have no score.
- `hybrid`: the existing generator, using at most 60 seconds for CP, then direct
  Monte Carlo evaluation and assignment/order local search in the remainder.

Record actual wall and CPU time, preparation, early stopping, candidate counts,
failures and censored evaluations. Equal upper budgets do not imply equal
consumed effort. Common setup and independent validation are additional costs.

Freeze all nine generation records and every selected plan before producing
the fresh `planner-comparison-holdout-v1` bank: 1024 scenarios per instance and
law F1/F2. DES/DAG cover the whole bank; original S1 covers 128 fixed scenarios
per plan/law. F1 is primary; F2 is a secondary changed-regime check. Three search
seeds and repeated plans do not multiply the independent production sample.

There are 36 fixed hybrid-versus-baseline comparisons: three instances, three
seeds, two baselines and two laws. Four one-sided exact binomial bounds per
comparison use alpha=0.05/144, giving joint coverage at least 95%. Select no seed
using validation outcomes. Claim a clear practical benefit for a registered
instance/seed only if its F1 lower differences against both baselines are
positive and its actual optimization wall cost is no greater than either.
Report cost/probability tradeoffs separately. Exact identical schedules obtained
more cheaply are a separate valid outcome; nonsignificance is not equivalence.

The possible mechanism is a different search over assignments and order under
the probability objective, beyond reranking nominal incumbents. Neither a new
optimizer nor SIMPAT superiority is claimed. A baseline victory is retained as
the practical result. This comparison does not validate worst-regime or Pareto
quality, which remain separately selectable interfaces.
