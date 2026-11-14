"""CUDD cofactor queries with exact category aggregation and full witnesses."""
from itertools import product
from time import perf_counter
from dd.cudd import BDD
from simpat_core.cudd_comparison_v2 import Cudd
from .model import validate
from .targets import estimate


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
        counts = {name:[0,0] for name in names}; certs = []
        for row in self.model['observation_categories']:
            known = {k:v for k,v in zip(self.model['signal_ids'],row['values']) if v is not None}
            restricted = {name:self.bdd.let(known,self.roots[name]) for name in names}
            extrema = {}
            for name, root in restricted.items():
                lo,hi = int(root == self.bdd.true),int(root != self.bdd.false)
                counts[name][0] += row['count']*lo; counts[name][1] += row['count']*hi
                if witnesses:
                    endpoints = []
                    for value in (lo,hi):
                        region = self.bdd.cube(known) & (self.roots[name] if value else ~self.roots[name])
                        witness = self.bdd.pick(region,care_vars=set(self.model['signal_ids']))
                        if witness is None:
                            raise ValueError('endpoint witness missing')
                        endpoints.append([bool(witness[k]) for k in self.model['signal_ids']])
                    extrema[name] = dict(minimum=lo,maximum=hi,
                                        lower_witness=endpoints[0],upper_witness=endpoints[1])
            if witnesses:
                certs.append(dict(values=row['values'],count=row['count'],extrema=extrema))
        result = dict(estimates={name:estimate(*pair,self.model['sample_count']) for name,pair in counts.items()},
                      samples=self.model['sample_count'],
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
