"""Completion-image operations from the published completion_target_v1 interface."""
from collections import Counter
from fractions import Fraction

AGGREGATE = '__logical_completions__'


def conjunction(values):
    values = list(values)
    if any(v is not None and type(v) is not bool for v in values):
        raise ValueError('completion coordinates must be Boolean or unknown')
    return False if False in values else True if all(v is True for v in values) else None


def estimate(lower, upper, count):
    if not 0 <= lower <= upper <= count or not count:
        raise ValueError('invalid integer extrema census')
    lo, hi = Fraction(lower, count), Fraction(upper, count)
    return dict(lower_exact=str(lo), upper_exact=str(hi), lower=float(lo), upper=float(hi),
                guaranteed=lower, possible=upper, samples=count,
                status='point' if lo == hi else 'interval')


def project_full(model):
    counts = Counter()
    positions = [model['signal_ids'].index(k) for k in model['completion_signals']]
    timely = model['signal_ids'].index(model['timely_signal'])
    for row in model['observation_categories']:
        key = (row['values'][timely], conjunction(row['values'][i] for i in positions))
        counts[key] += row['count']
    return dict(signal_ids=['timely', AGGREGATE], sample_count=model['sample_count'],
                observation_categories=[dict(values=list(v), count=n)
                    for v, n in sorted(counts.items(), key=lambda p: str(p[0]))])


def query_reduced(model):
    lower = upper = total = 0
    for row in model['observation_categories']:
        value = conjunction(row['values']); n = row['count']
        lower += n * (value is True); upper += n * (value is not False); total += n
    if total != model['sample_count']:
        raise ValueError('reduced count differs')
    return estimate(lower, upper, total)


def query_full_r(model):
    positions = [model['signal_ids'].index(k) for k in model['completion_signals']]
    positions.append(model['signal_ids'].index(model['timely_signal']))
    lower = upper = total = 0
    for row in model['observation_categories']:
        value = conjunction(row['values'][i] for i in positions); n = row['count']
        lower += n * (value is True); upper += n * (value is not False); total += n
    if total != model['sample_count']:
        raise ValueError('full count differs')
    return estimate(lower, upper, total)


def direct(rows, completions):
    counts = Counter((row['timely'], conjunction(row[k] for k in completions)) for row in rows)
    return dict(signal_ids=['timely', AGGREGATE], sample_count=sum(counts.values()),
                observation_categories=[dict(values=list(v), count=n)
                    for v, n in sorted(counts.items(), key=lambda p: str(p[0]))])


def collapsed(model):
    """Exact completion-image combination baseline; preserve the joint controls."""
    from copy import deepcopy
    result = deepcopy(model)
    controls = [k for k in model['signal_ids'] if k not in model['completion_signals']]
    positions = [model['signal_ids'].index(k) for k in controls]
    cs = [model['signal_ids'].index(k) for k in model['completion_signals']]
    counts = Counter()
    for row in model['observation_categories']:
        counts[tuple(row['values'][i] for i in positions) + (conjunction(row['values'][i] for i in cs),)] += row['count']
    result['signal_ids'] = controls + [AGGREGATE]
    result['completion_signals'] = [AGGREGATE]
    result['entry_completion_signal'] = AGGREGATE
    result['required_edge_completions'] = [dict(edge_id=r['edge_id'], signal=AGGREGATE)
                                          for r in model['required_edge_completions']]
    result['observation_categories'] = [dict(values=list(v), count=n) for v,n in sorted(counts.items(),key=lambda p:str(p[0]))]
    return result
