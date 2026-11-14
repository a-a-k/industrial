"""Per-condition binomial inference using whole-batch replication counts."""
from scipy.stats import beta


def lower(k,n,alpha):
    if not 0 <= k <= n or n <= 0: raise ValueError('invalid binomial count')
    return 0. if k == 0 else float(beta.ppf(alpha,k,n-k+1))


def upper(k,n,alpha):
    if not 0 <= k <= n or n <= 0: raise ValueError('invalid binomial count')
    return 1. if k == n else float(beta.ppf(1-alpha,k+1,n-k))


def outer(guaranteed,possible,n,alpha=.05):
    if guaranteed > possible: raise ValueError('inverted success counts')
    return [lower(guaranteed,n,alpha/2),upper(possible,n,alpha/2)]


def forecast_metrics(prediction, successes, n_test):
    km,kp,n = prediction['guaranteed'],prediction['possible'],prediction['samples']
    lo,hi = prediction['lower'],prediction['upper']; freq = successes/n_test
    point = lo if km == kp else None
    cal_lo,cal_hi = lower(km,n,.0125),upper(kp,n,.0125)
    test_lo,test_hi = lower(successes,n_test,.0125),upper(successes,n_test,.0125)
    return dict(calibration_attempts=n,validation_attempts=n_test,validation_successes=successes,
        validation_frequency=freq,validation_ci95=outer(successes,successes,n_test),
        prediction=[lo,hi],prediction_width=hi-lo,calibration_outer95=outer(km,kp,n),
        signed_error=None if point is None else point-freq,
        absolute_error=None if point is None else abs(point-freq),
        empirical_error_range=[lo-freq,hi-freq],distance_to_frequency=max(lo-freq,freq-hi,0.),
        discrepancy_outer95=[cal_lo-test_hi,cal_hi-test_lo],
        confidence_scope='one condition; four one-sided 98.75% bounds',
        replication_unit='complete fixed batch')
