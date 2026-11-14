"""Industrial schema: the published predicates and Cartesian observation fibers."""
from collections import Counter
from copy import deepcopy
from simpat_core.graph_execution_model_v1 import control_ids, predicates

VERSION = 'industrial-cartesian-joint-v1'


class Unsupported(ValueError):
    pass


def validate(model):
    if model['version'] != VERSION or model['execution_class'] != 'declared_mandatory_call_groups':
        raise ValueError('unsupported industrial model')
    ids = model['signal_ids']; known = set(ids)
    if not ids or len(ids) != len(known):
        raise ValueError('invalid observation coordinates')
    services = set(model['graph']['services'])
    if services != set(model['replicas']) or len(services) != len(model['graph']['services']):
        raise ValueError('invalid services')
    state_ids = set()
    for replicas in model['replicas'].values():
        if not replicas:
            raise ValueError('no replica')
        for gates in replicas:
            if len(gates) != len(set(gates)) or not set(gates) <= known:
                raise ValueError('invalid replica gate')
            state_ids.update(gates)
    edge_ids = set()
    for edge in model['graph']['edges']:
        if (edge['source'] not in services or edge['target'] not in services or
                edge['type'] not in ('sync','async') or edge['id'] in edge_ids or
                not set(edge['factors']) <= known):
            raise ValueError('invalid graph edge')
        edge_ids.add(edge['id']); state_ids.update(edge['factors'])
    op = model['operation']
    if (op['semantics'] != 'immediate_sync_all_required' or op['entry'] not in services or
            not op['required'] or not set(op['required']) <= services):
        raise ValueError('invalid operation')
    demands = set(); controlled = set()
    for row in model['demand_controls']:
        service = row['service']; signals = row['selected_signals']
        if (service in controlled or service not in op['required'] or
                len(signals) != len(model['replicas'][service]) or
                len(signals) != len(set(signals)) or not set(signals) <= known or
                set(signals) & (demands | state_ids)):
            raise ValueError('invalid demand control')
        controlled.add(service); demands.update(signals)
    timely = model['timely_signal']; completion = model['completion_signals']
    if timely not in known or timely in state_ids | demands:
        raise ValueError('aliased deadline')
    if (not completion or len(completion) != len(set(completion)) or
            not set(completion) <= known or set(completion) & (state_ids | demands | {timely})):
        raise ValueError('invalid completion signals')
    bindings = model['required_edge_completions']
    if (len(bindings) != len({r['edge_id'] for r in bindings}) or
            any(r['signal'] not in completion for r in bindings)):
        raise ValueError('invalid required edge completion')
    if (model['entry_completion_signal'] not in completion or
            set(completion) != {model['entry_completion_signal']} | {r['signal'] for r in bindings} or
            known != state_ids | demands | {timely} | set(completion)):
        raise ValueError('unused or missing coordinate')
    total = 0; categories = set()
    for row in model['observation_categories']:
        values = tuple(row['values'])
        if (len(values) != len(ids) or any(v is not None and type(v) is not bool for v in values) or
                values in categories or type(row['count']) is not int or row['count'] <= 0):
            raise ValueError('invalid observation category')
        categories.add(values); total += row['count']
    if not total or type(model['sample_count']) is not int or total != model['sample_count']:
        raise ValueError('invalid sample census')


def identify(schema, observations):
    model = deepcopy(schema)
    ids = model['signal_ids']; counts = Counter()
    for row in observations:
        if set(row) != set(ids):
            raise ValueError('observation coordinate mismatch')
        values = tuple(row[k] for k in ids)
        if any(v is not None and type(v) is not bool for v in values):
            raise ValueError('invalid observation value')
        counts[values] += 1
    model.update(version=VERSION, execution_class='declared_mandatory_call_groups',
        sample_count=sum(counts.values()), family='cartesian_known_coordinate_fibers',
        observation_categories=[dict(values=list(v), count=n) for v,n in sorted(counts.items(),key=lambda p:str(p[0]))])
    validate(model)
    return model


def make_schema(graph, replicas, operation, demand_controls, bindings,
                entry_completion='entry_completed', timely='timely'):
    cs = sorted({entry_completion} | {r['signal'] for r in bindings})
    model = dict(version=VERSION, execution_class='declared_mandatory_call_groups',
        graph=deepcopy(graph), replicas=deepcopy(replicas), operation=deepcopy(operation),
        demand_controls=deepcopy(demand_controls), required_edge_completions=deepcopy(bindings),
        completion_signals=cs, entry_completion_signal=entry_completion, timely_signal=timely,
        assumptions=dict(family='cartesian_known_coordinate_fibers',
                         physical_constraints_added=False, external_labels_used=False))
    model['signal_ids'] = sorted(control_ids(model) | set(cs))
    return model
