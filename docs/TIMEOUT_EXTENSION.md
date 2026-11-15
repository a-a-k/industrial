# Extended measurements of censored cost cases

Repeat only the two Mk10/F2/MCAR30/100000 cases whose twelve fresh processes
all reached the original 300-second limit. Both methods in each case receive
1200 seconds per process. Keep the original inputs, method implementations,
one warmup and five measured fresh processes, one CPU and 4 GiB. Each complete
pair remains on one runner. The job limit is 270 minutes; unfinished jobs reserve
that full limit against the unchanged 72 runner-hour campaign budget.

Before timing, verify the existing preparation/method qualification and the
exact bytes of the regenerated gzip log and contract against the old release.
The method order remains the same deterministic randomized order. Input
preparation, verification, warmups, failures and all timed attempts are charged.

The 300-second primary series and its PARTIAL status remain unchanged. Publish
these 1200-second repeats as a separate supplement. Do not mix their times with
the original series as if the resource limits were identical. A repeated timeout
remains censored; no speedup or successful completion is assumed in advance.
