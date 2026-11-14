"""Versioned evidence binding; no external outcome or hidden calendar inputs."""
from collections import defaultdict
from .common import digest, canonical, uniform
from .model import make_schema, identify, Unsupported
from .targets import conjunction

FORBIDDEN = {'mission_success','expected_success','Y','external_outcomes','failures','calendars','products'}


def reject_forbidden(value):
    if isinstance(value,dict):
        if FORBIDDEN & set(value):
            raise ValueError('forbidden identification input')
        for v in value.values(): reject_forbidden(v)
    elif isinstance(value,list):
        for v in value: reject_forbidden(v)


def node(i): return f'op:{i:04d}'
def xkey(i,m): return f'x:{i:04d}:{m:03d}'
def dkey(i,m): return f'd:{i:04d}:{m:03d}'
def ckey(j): return f'completed:{j:03d}'


def schema(contract):
    ops = contract['operations']; ids = {o['id'] for o in ops}
    if ids != set(range(len(ops))) or not contract['jobs']:
        raise Unsupported('invalid operation identities')
    vertices = ['dispatch'] + [node(o['id']) for o in ops]
    replicas = {'dispatch':[[]]}; edges = []; controls = []; bindings = []
    mandatory = {o['id'] for o in ops if not o.get('optional',False)}
    for op in ops:
        i = op['id']; alternatives = op['compatible_machines']
        if not alternatives or len(alternatives) != len(set(alternatives)):
            raise Unsupported('invalid compatible executors')
        replicas[node(i)] = [[xkey(i,m)] for m in alternatives]
        if i in mandatory:
            controls.append(dict(service=node(i),selected_signals=[dkey(i,m) for m in alternatives]))
        parents = op['predecessors'] or [None]
        for parent in parents:
            if parent is not None and parent not in ids:
                raise Unsupported('unexplained required boundary')
            if i in mandatory and parent is not None and parent not in mandatory:
                raise Unsupported('optional prerequisite of mandatory operation')
            edge_id = f'{parent if parent is not None else "dispatch"}->{i}'
            edges.append(dict(id=edge_id,source='dispatch' if parent is None else node(parent),
                              target=node(i),type='sync' if i in mandatory else 'async',factors=[]))
            if i in mandatory:
                bindings.append(dict(edge_id=edge_id,signal=ckey(op['job'])))
    required = [node(i) for i in sorted(mandatory)]
    return make_schema(dict(services=vertices,edges=edges),replicas,
        dict(id=contract['id'],entry='dispatch',required=required,semantics='immediate_sync_all_required'),
        controls,bindings,entry_completion='C_dispatch')


def consistent(values):
    values = list(values)
    return values[0] if values and all(v == values[0] for v in values) else None


def bind(contract, attempts, records, deadline):
    proto = schema(contract)
    ops = {o['id']:o for o in contract['operations']}
    attempt_ids = [a['id'] for a in attempts]
    if not attempts or len(attempt_ids) != len(set(attempt_ids)):
        raise ValueError('invalid attempt census')
    by_attempt = defaultdict(list)
    registered = set(attempt_ids)
    for record in records:
        if record['attempt'] not in registered:
            raise ValueError('unregistered attempt')
        if record['kind'] == 'reassign':
            raise Unsupported('reassignment')
        if 'op' in record and record['op'] not in ops:
            raise Unsupported('unexplained required operation')
        if 'op' in record and 'parents' in record:
            if any(p not in ops for p in record['parents']):
                raise Unsupported('unexplained required parent')
            if sorted(record['parents']) != sorted(ops[record['op']]['predecessors']):
                raise Unsupported('causal relation differs from declared structure')
        if record['kind'] in ('assignment','receipt') and record['machine'] not in ops[record['op']]['compatible_machines']:
            raise Unsupported('unclassified executor')
        by_attempt[record['attempt']].append(record)
    observations = []; audits = []
    for attempt in attempts:
        row = dict.fromkeys(proto['signal_ids']); rows = by_attempt[attempt['id']]
        if attempt.get('compute_status','OK') != 'OK':
            observations.append(row); audits.append(dict(id=attempt['id'],status='COMPUTATION_UNAVAILABLE')); continue
        end = attempt.get('finished_at')
        if end is not None:
            row['timely'] = end <= deadline
        elif attempt['observed_until'] >= deadline:
            row['timely'] = False
        accepted = [r['value'] for r in rows if r['kind']=='dispatch']
        row['C_dispatch'] = consistent(accepted)
        window_end = min(deadline,attempt['observed_until'],end if end is not None else attempt['observed_until'])
        selections = defaultdict(list);receipts_by_op = defaultdict(list);postconditions = defaultdict(list)
        for record in rows:
            if record['kind']=='assignment' and record.get('closed',False):
                selections[record['op']].append(record['machine'])
            elif record['kind']=='receipt':
                receipts_by_op[(record['op'],record['machine'])].append(record)
            elif record['kind']=='postcondition':
                postconditions[record['job']].append(record['value'])
        for i,op in ops.items():
            actual = consistent(selections[i])
            for m in op['compatible_machines']:
                dk = dkey(i,m)
                if dk in row and actual is not None:
                    row[dk] = actual == m
                receipts = [r for r in receipts_by_op[(i,m)] if attempt['started_at'] <= r['time'] <= window_end]
                if receipts:
                    row[xkey(i,m)] = True
        for job in contract['jobs']:
            key = ckey(job)
            if key in row:
                row[key] = consistent(postconditions[job])
        observations.append(row)
        audits.append(dict(id=attempt['id'],status='SUPPORTED',known=sum(v is not None for v in row.values())))
    return proto,observations,audits


def fit(packet, deadline):
    reject_forbidden(packet)
    proto,rows,audit = bind(packet['contract'],packet['attempts'],packet['records'],deadline)
    model = identify(proto,rows)
    model['binding_version'] = 'industrial-receipt-selection-postcondition-v1'
    model['contract_sha256'] = digest(canonical(packet['contract']))
    model['deadline'] = deadline
    return model,rows,audit


def mask(packet, mode, labels=None):
    if mode == 'available': return packet
    records = []
    for record in packet['records']:
        aid = record['attempt']
        if mode == 'trace_loss':
            drop = uniform('whole-trace',packet['contract']['id'],aid) < .1
        else:
            if mode in ('mcar10','mcar30'):
                p = .1 if mode == 'mcar10' else .3
                purpose = 'nested-mask'
            elif mode == 'informative':
                if labels is None or aid not in labels:
                    raise ValueError('masker lacks external label')
                p = .1 if labels[aid] else .5; purpose = 'informative-mask'
            else:
                raise ValueError('unknown observation mode')
            drop = uniform(purpose,packet['contract']['id'],aid,record['record_id']) < p
        if not drop: records.append(record)
    return dict(contract=packet['contract'],attempts=packet['attempts'],records=records)


def packet_rows(contract, attempts, records):
    """Stable serialization independent of producer record order."""
    return dict(contract=contract,attempts=sorted(attempts,key=lambda a:a['id']),
                records=sorted(records,key=lambda r:(r['attempt'],r['record_id'])))
