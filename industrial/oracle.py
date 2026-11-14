"""Independent scalar formulas, compatible-state enumeration and certificate checks."""
from itertools import product
from .targets import estimate


def evaluate(model, state):
    active = {}
    for vertex, replicas in model['replicas'].items():
        active[vertex] = any(all(state[key] for key in replica) for replica in replicas)
    reached = {model['operation']['entry']} if active[model['operation']['entry']] else set()
    changed = True
    while changed:
        changed = False
        for edge in model['graph']['edges']:
            if (edge['type'] == 'sync' and edge['source'] in reached and
                    active[edge['target']] and all(state[k] for k in edge['factors']) and
                    edge['target'] not in reached):
                reached.add(edge['target']); changed = True
    b = all(v in reached for v in model['operation']['required'])
    s = b
    for row in model['demand_controls']:
        choices = [state[k] for k in row['selected_signals']]
        available = [all(state[k] for k in replica) for replica in model['replicas'][row['service']]]
        s = s and any(choices) and all(not d or x for d,x in zip(choices,available))
    edge_ids = {e['id'] for e in model['graph']['edges'] if e['type']=='sync'}
    c = state[model['entry_completion_signal']]
    for row in model['required_edge_completions']:
        c = c and row['edge_id'] in edge_ids and state[row['signal']]
    t = state[model['timely_signal']]
    e = bool(s and c and t)
    values = dict(reachability=bool(b),selected=bool(s),without_deadline=bool(s and c),
        execution=e,without_selection=bool(b and c and t),without_completion=bool(s and t))
    for name in tuple(values):
        if name != 'execution':
            values[name+'_minus_execution'] = int(values[name])-int(e)
    r = bool(t and all(state[k] for k in model['completion_signals']))
    values['R'] = r; values['R_minus_execution'] = int(r)-int(e)
    return values


def compatible(model, values):
    unknown = [i for i,v in enumerate(values) if v is None]
    for bits in product((False,True),repeat=len(unknown)):
        complete = list(values)
        for i,bit in zip(unknown,bits):
            complete[i] = bit
        yield dict(zip(model['signal_ids'],complete))


def enumerate_model(model, names=None, physical=None):
    totals = {}; images = []
    for row in model['observation_categories']:
        evaluated = [evaluate(model,state) for state in compatible(model,row['values'])
                     if physical is None or physical(state)]
        if not evaluated:
            raise ValueError('empty restricted fiber')
        panel = list(evaluated[0]) if names is None else list(names)
        images.append({tuple(int(v[k]) for k in panel) for v in evaluated})
        for name in panel:
            pair = totals.setdefault(name,[0,0])
            pair[0] += row['count']*min(int(v[name]) for v in evaluated)
            pair[1] += row['count']*max(int(v[name]) for v in evaluated)
    return dict(estimates={k:estimate(*v,model['sample_count']) for k,v in totals.items()},images=images)


def verify_certificates(model, result):
    certs = result['category_certificates']
    if len(certs) != len(model['observation_categories']):
        raise ValueError('certificate census mismatch')
    totals = {k:[0,0] for k in result['estimates']}; checked = 0
    for row,cert in zip(model['observation_categories'],certs):
        if row['values'] != cert['values'] or row['count'] != cert['count'] or set(cert['extrema']) != set(totals):
            raise ValueError('certificate category mismatch')
        for name,ex in cert['extrema'].items():
            for side,key in enumerate(('lower_witness','upper_witness')):
                witness = ex[key]
                if len(witness) != len(model['signal_ids']) or any(type(v) is not bool for v in witness):
                    raise ValueError('incomplete witness')
                if any(v is not None and v != w for v,w in zip(row['values'],witness)):
                    raise ValueError('witness violates known coordinates')
                endpoint = ex['minimum' if side == 0 else 'maximum']
                if int(evaluate(model,dict(zip(model['signal_ids'],witness)))[name]) != endpoint:
                    raise ValueError('witness does not attain endpoint')
                totals[name][side] += row['count']*endpoint; checked += 1
    for name,pair in totals.items():
        if estimate(*pair,model['sample_count']) != result['estimates'][name]:
            raise ValueError('certificate weights do not reproduce bounds')
    return dict(complete_witnesses=checked,categories=len(certs))
