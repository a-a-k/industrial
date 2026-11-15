"""CUDD cofactor queries with exact category aggregation and full witnesses."""
from itertools import product
from time import perf_counter
from dd.cudd import BDD
from simpat_core.cudd_comparison_v2 import Cudd
from .model import validate
from .targets import estimate

ANALYSIS_VERSION = 'industrial-cudd-cofactor-witness-v2'


class Compiled:
    def __init__(self, model):
        started = perf_counter(); validate(model)
        self.model = model
        self.backend = Cudd(sift=False)
        self.backend.bdd = BDD(memory_estimate=2**30, initial_cache_size=2**14)
        self.bdd = self.backend.bdd
        self.bdd.configure(reordering=False)
        order = []
        for service in model['graph']['services']:
            order.extend(x for gates in model['replicas'][service] for x in gates)
            order.extend(x for row in model['demand_controls'] if row['service'] == service
                         for x in row['selected_signals'])
            order.extend(x for e in model['graph']['edges'] if e['source'] == service for x in e['factors'])
        order += model['completion_signals'] + [model['timely_signal']]
        order = list(dict.fromkeys(order))
        if set(order) != set(model['signal_ids']):
            raise ValueError('variable ordering mismatch')
        self.bdd.declare(*order)
        self.backend.rebuild(model)
        self.roots = self.backend.roots
        r = self.bdd.var(model['timely_signal'])
        for name in model['completion_signals']:
            r &= self.bdd.var(name)
        self.roots['R'] = r
        self.roots['R_minus_execution'] = r & ~self.roots['execution']
        self.build_seconds = perf_counter()-started

    def solve(self, names=None, witnesses=False):
        validate(self.model)
        names = list(self.roots) if names is None else list(names)
        if not set(names) <= set(self.roots):
            raise ValueError('unsupported target')
        counts = {name:[0,0] for name in names}; certs = []; native_picks=0
        for row in self.model['observation_categories']:
            known = {k:v for k,v in zip(self.model['signal_ids'],row['values']) if v is not None}
            unique = {root:self.bdd.let(known,root) for root in {self.roots[name] for name in names}}
            restricted = {name:unique[self.roots[name]] for name in names}
            if witnesses:
                unknown = set(self.model['signal_ids'])-set(known)
                canonical = [False if v is None else v for v in row['values']]
                endpoint_cache = {}
            extrema = {}
            for name, root in restricted.items():
                lo,hi = int(root == self.bdd.true),int(root != self.bdd.false)
                counts[name][0] += row['count']*lo; counts[name][1] += row['count']*hi
                if witnesses:
                    if lo==hi:
                        endpoints=[canonical,canonical]
                    else:
                        endpoints=[]
                        for value in (lo,hi):
                            key=(root,value)
                            if key not in endpoint_cache:
                                region=root if value else ~root
                                assignment=self.bdd.pick(region,care_vars=unknown);native_picks+=1
                                if assignment is None:raise ValueError('endpoint witness missing')
                                complete=dict(known);complete.update(assignment)
                                endpoint_cache[key]=[bool(complete[k]) for k in self.model['signal_ids']]
                            endpoints.append(endpoint_cache[key])
                    extrema[name] = dict(minimum=lo,maximum=hi,
                                        lower_witness=endpoints[0],upper_witness=endpoints[1])
            if witnesses:
                certs.append(dict(values=row['values'],count=row['count'],extrema=extrema))
        result = dict(estimates={name:estimate(*pair,self.model['sample_count']) for name,pair in counts.items()},
                      samples=self.model['sample_count'],
                      analysis_version=ANALYSIS_VERSION,
                      native_witness_picks=native_picks,
                      family='cartesian_known_coordinate_fibers',
                      interval_is_confidence_interval=False)
        if witnesses:
            result['category_certificates'] = certs
        return result

    def vectors(self, values, names):
        known = {k:v for k,v in zip(self.model['signal_ids'],values) if v is not None}
        cube = self.bdd.cube(known)
        result = set()
        def visit(index, region, bits):
            if region == self.bdd.false: return
            if index == len(names):
                result.add(bits); return
            root = self.roots[names[index]]
            visit(index+1,region & ~root,bits+(0,))
            visit(index+1,region & root,bits+(1,))
        visit(0,cube,())
        return result
