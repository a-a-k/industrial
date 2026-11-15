# Reproduction and evidence interfaces

Computation runs on standard GitHub-hosted Ubuntu runners. The container digest,
CPython patch version, Python wheel hashes, Go version, compiler flags, source
commits and attempt-seed domain are versioned. No workflow uses Actions artifact
storage or cache. Complete public evidence is transferred through Releases.

## Sources and environment

`provenance/sources.json` identifies the source snapshots and frozen module
checksums. The `simpat_core` package changes package initialization only: its
scientific modules are unchanged published files. The original package remains
available for its original regression. Industrial validation and witness queries
are explicit separate modules; the published control/coordinate caps are not
globally patched.

`industrial-environment-v1` contains the complete wheel collection and a
hash-required lock file. The CPython 3.11 CUDD extension is installed from that
collection, not rebuilt implicitly for another interpreter.

The private S1 participant requires a read-only `TSFG_SOURCE_SSH_KEY` secret.
Its original regression evidence is reusable only for the same source commit
and Go version. Public adapters are compiled with the unchanged kernel. Private
source and binaries are never included in evidence. `PUBLIC_ONLY=1` builds the
independent public DES/DAG executable without S1 access.

## Fixed workflow order

1. Freeze the environment with `environment.yml` once.
2. Run `qualify.yml`; require `CORE_PASS`, not merely a green workflow. Inspect
   `qualification.json`, exhaustive controls and independent label-mutation replay.
3. Run `production.yml` with stage `preflight` and that qualification release.
   This freezes all schedules/schemas and checks the maximum Cartesian fibers
   and nominal execution with all three engines.
4. Acquire only Mk01-F1 calibration, then run `identify.yml` on its observation
   release. Require all fifteen cases, three refinement checks and fresh-model
   replay to pass before opening the other nineteen calibration conditions.
5. Acquire and independently identify the remaining calibration conditions.
6. Run `control.yml` task `seal` with all twenty calibration fit releases.
7. Acquire validation only against that immutable seal. No validation outcome is
   opened during forecast identification.
8. Run `identify.yml` purpose `validation_reanalysis` for descriptive E4 checks.
   These models never replace the sealed forecasts.
9. Run `control.yml` task `evaluate` using the explicit fit, bank, seal and
   descriptive-analysis registry.
10. Execute the declared paired cases in `provenance/measurements.json` through
    `measure.yml`; then run `control.yml` task `report` with their exact releases.

Source edits that change the qualified implementation invalidate its fingerprint.
Replaced preflight evidence remains published and is listed separately in
`provenance/superseded.json`; it is not pooled with the primary bank.

## Release contents

- `qualification-*`: exact controls, synthetic native inputs and independent
  kernel outputs, full-state/mask regression and source provenance.
- `preflight-*`: pinned raw instances, frozen schedules, state schemas, nominal
  outputs and maximum-fiber feasibility/certificate checks.
- `calibration-bank-*` / `validation-bank-*`: histories, trajectories, process
  statuses and separate finished-product accounting.
- `*-observations-*`: contract, complete attempt journals and permitted records
  only, across the declared deadlines and observation masks.
- `fit-*`: calibration empirical laws, bounds, full witnesses, independent
  checks, reduced/combination models, fresh-process replay and forecasts.
- `seal-*`: fixed forecast identities before validation acquisition.
- `reanalysis-*`: descriptive validation laws and E4 checks, not forecasts.
- `evaluation-*`: independent outcomes, calibration-frequency comparators,
  signed errors and per-condition confidence regions.
- `measurement-*`: every warmup/repeat, failures, timeouts, phases, peak RSS,
  representation sizes, paired signatures, preparation costs and hardware limits.
- `final-report-*`: machine-readable acceptance, Russian report, tables, exact
  release registry and complete workflow history.

Each release has a receipt with archive/part checksums and a `SHA256SUMS.json`
file manifest. `industrial.releases.fetch` verifies both before extraction.

## Interpreting measurements

Full-R uses only the necessary completion/deadline query. Projection retains
the cost of constructing the full model before projection. Direct-R binds local
postconditions and timing without building X/D or a graph. The combination
baseline aggregates completion before joint-category counting and retains the
controls needed for the complete target panel.

Paired methods run sequentially in the same container. Each warmup and measured
repeat is a fresh process; operating-system caches are not forcibly flushed.
Saved-model queries separately report reading and ten in-process queries.
Replay loads retain original attempt identities as provenance and create unique
load identifiers; their statistical sample size does not increase. Their exact
canonical serialization and deterministic gzip stream can be reconstructed from
the retained packet and load rule.

Timeouts retain their 300-second censoring threshold. Ratios require five
correctly completed matched repeats. Missing calculations and unrun obligations
remain visible; a pilot or a faster direct method cannot satisfy an uncompleted
full-model obligation.
