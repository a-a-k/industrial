from copy import deepcopy
from itertools import product
from pathlib import Path
import unittest

from industrial.binding import fit,mask,ckey,xkey,dkey
from industrial.common import canonical,rng,write_json
from industrial.discovery import recover
from industrial.model import VERSION,identify,make_schema,Unsupported
from industrial.oracle import evaluate,enumerate_model,verify_certificates
from industrial.production import simulate,export_observations,product_ledger,outcomes,check_physics,compare
from industrial.solver import Compiled
from industrial.targets import query_full_r,project_full,query_reduced,direct,collapsed
from industrial.statistics import lower,upper,outer,forecast_metrics
from tests.test_frozen_core import make,row


def industrial(rows):
    model=make(rows);model['version']=VERSION
    return model


def tiny(works=(200,),machines=None,optional=False):
    machines=machines or [0]*len(works);queues=[[] for _ in range(max(machines)+1)];ops=[];tail=[0]*len(queues)
    for i,(work,machine) in enumerate(zip(works,machines)):
        is_optional=optional and i==0
        job=1 if is_optional else 0
        predecessors=[] if i==0 or optional else [i-1]
        ready=max(tail[machine],ops[i-1]['planned_end'] if predecessors else 0)
        ops.append(dict(id=i,job=job,machine=machine,work=work,release=0,planned_start=ready,
            planned_end=ready+work,predecessors=predecessors,optional=is_optional,
            alternatives=[dict(machine=machine,work=work)]))
        tail[machine]=ready+work;queues[machine].append(i)
    jobs=[dict(id=0,release=0,final_operation=len(ops)-1)]
    if optional:jobs.append(dict(id=1,release=0,final_operation=0,optional=True))
    return dict(dataset_id='E1-toy',operations=ops,queues=queues,jobs=jobs,delta=5,nominal_makespan=max(tail))


def produce(name,data,failures,horizon):
    scenario=dict(id=name,failures=failures,work_overrides=[])
    all_results=[]
    for engine in ('des','dag','tsfg'):
        result,processes=simulate(data,[scenario],Path('output/qualification/production')/name/engine,engine,horizon)
        if name not in result:raise AssertionError((engine,name,processes))
        check_physics(data,scenario,result[name]);all_results.append(result[name])
    compare(all_results[0],all_results[1]);compare(all_results[0],all_results[2])
    packet=export_observations(data,[scenario],{name:all_results[0]},horizon)
    ledger=product_ledger(data,[scenario],{name:all_results[0]})
    return packet,ledger,all_results[0]


class SemanticsE1(unittest.TestCase):
    def test_execution_and_horizon_semantics(self):
        cases=[('success',tiny(),[],500,500,True,True),
            ('queue_late',tiny((200,200)),[],500,300,True,False),
            ('initial_recovery',tiny(),[[0,0,200]],500,500,True,True),
            ('suspend_resume',tiny(),[[0,100,300]],500,500,True,True),
            ('unresolved',tiny((600,)),[],500,500,None,False),
            ('exact_horizon',tiny((500,)),[],500,500,True,True),
            ('optional_delay',tiny((200,200),optional=True),[],500,300,True,False)]
        summary=[]
        for name,data,failures,h,d,c,t in cases:
            with self.subTest(name=name):
                packet,ledger,trajectory=produce(name,data,failures,h)
                model,rows,_=fit(packet,d)
                self.assertIs(rows[0][ckey(0)],c);self.assertIs(rows[0]['timely'],t)
                y=outcomes(ledger,[0],d)[name]
                answer=Compiled(model).solve(['execution','R'])['estimates']
                self.assertEqual(answer['execution']['lower'],int(y))
                self.assertEqual(answer['execution']['upper'],int(y))
                if name=='initial_recovery':self.assertEqual(trajectory['start'],[200])
                if name=='suspend_resume':self.assertEqual(trajectory['finish'],[400])
                if name=='unresolved':self.assertIsNone(trajectory['finish'][0])
                summary.append(dict(case=name,C=c,T=t,Y=y))
        write_json('output/qualification/E1-cases.json',summary)

    def test_quality_failure_delivery_loss_and_refusal(self):
        data=tiny();data['quality_results']={'0':False}
        packet,ledger,_=produce('quality_failure',data,[],500)
        model,rows,_=fit(packet,500)
        self.assertIs(rows[0][ckey(0)],False);self.assertIs(rows[0]['timely'],True)
        self.assertFalse(outcomes(ledger,[0],500)['quality_failure'])
        self.assertEqual(Compiled(model).solve(['execution'])['estimates']['execution']['upper'],0)
        missing=deepcopy(packet);missing['records']=[r for r in missing['records'] if r['kind']!='postcondition']
        self.assertIsNone(fit(missing,500)[1][0][ckey(0)])
        missing=deepcopy(packet);missing['records']=[r for r in missing['records'] if r['kind']!='receipt']
        self.assertIsNone(fit(missing,500)[1][0][xkey(0,0)])
        for bad in (dict(kind='reassign',attempt='quality_failure'),
                    dict(kind='receipt',attempt='quality_failure',op=0,machine=0,time=0,parents=[99])):
            altered=deepcopy(packet);altered['records'].append(bad)
            with self.assertRaises(Unsupported):fit(altered,500)

    def test_computational_timeout_is_not_production_failure(self):
        data=tiny();packet=export_observations(data,[dict(id='timeout')],{},500)
        _,rows,_=fit(packet,500)
        self.assertTrue(all(v is None for v in rows[0].values()))
        self.assertIsNone(rows[0]['timely'])


class IdentificationE2(unittest.TestCase):
    def packet(self):
        data=tiny((100,100));packet,_,_=produce('E2-reference',data,[],500)
        a=deepcopy(packet['attempts'][0]);a['id']='second';packet['attempts'].append(a)
        packet['records'] += [dict(r,attempt='second') for r in list(packet['records'])]
        return packet

    def test_hand_census_transformations_and_label_independence(self):
        packet=self.packet();model,rows,_=fit(packet,500)
        self.assertEqual(model['sample_count'],2);self.assertEqual(len(model['observation_categories']),1)
        self.assertEqual(model['observation_categories'][0]['count'],2)
        self.assertEqual(len(model['graph']['services']),3)
        self.assertEqual(len(model['graph']['edges']),2)
        self.assertTrue(all(v is True for row_ in rows for v in row_.values()))
        shuffled=deepcopy(packet);rng('permutation').shuffle(shuffled['records'])
        self.assertEqual(fit(shuffled,500)[0],model)
        lost=deepcopy(packet);lost['records']=[r for r in lost['records'] if r['attempt']!='second']
        lm,lr,_=fit(lost,500)
        self.assertEqual(lm['sample_count'],2);self.assertIsNone(lr[1][ckey(0)])
        self.assertIs(lr[1]['timely'],True)
        conflict=deepcopy(packet);conflict['records'].append(dict(attempt='second',record_id='conflict',kind='postcondition',job=0,value=False))
        self.assertIsNone(fit(conflict,500)[1][1][ckey(0)])
        lost_stage=deepcopy(packet);lost_stage['records']=[r for r in lost_stage['records'] if r.get('op')!=1]
        self.assertIsNone(fit(lost_stage,500)[1][0][dkey(1,0)])
        for value in (True,False):
            with self.assertRaises(ValueError):fit(dict(packet,Y=value),500)
        original=canonical(fit(packet,500)[0])
        external_labels=[True,False];external_labels=[not x for x in external_labels]
        self.assertEqual(canonical(fit(packet,500)[0]),original)

    def test_equal_marginal_joint_laws(self):
        common=industrial([row(entry_completed=False,call_completed=False),row()])
        exclusive=industrial([row(entry_completed=False),row(call_completed=False)])
        self.assertEqual(Compiled(common).solve(['execution'])['estimates']['execution']['lower'],.5)
        self.assertEqual(Compiled(exclusive).solve(['execution'])['estimates']['execution']['upper'],0)
        good=industrial([row(a=False,da=True,db=False),row(a=False,da=False,db=True)])
        bad=industrial([row(a=False,da=True,db=True)]*2)
        self.assertEqual(Compiled(good).solve(['execution'])['estimates']['execution']['lower'],.5)
        self.assertEqual(Compiled(bad).solve(['execution'])['estimates']['execution']['upper'],0)
        self.assertEqual([sum(word[i]=='A' for word in ('AA','BB')) for i in (0,1)],
                         [sum(word[i]=='A' for word in ('AB','BA')) for i in (0,1)])

    def test_graph_recovery_with_observation_probability(self):
        truth={(0,1),(0,2),(1,3),(2,3),(3,4),(3,5)};summary=[]
        for p in (0,.01,.1,.5,1):
            missing={n:0 for n in (16,64,256,1024)}
            for replicate in range(256):
                source=rng('discovery',p,replicate);records=[]
                for attempt in range(1,1025):
                    records.extend(dict(source=s,target=t,attempt=attempt) for s,t in sorted(truth) if source.random()<p)
                    if attempt in missing:
                        observed=set(recover(range(6),records))
                        self.assertTrue(observed<=truth)
                        missing[attempt]+=len(truth-observed)
                        if p==0:self.assertFalse(observed)
                        if p==1:self.assertEqual(observed,truth)
            summary.extend(dict(p=p,n=n,missing=miss,edge_sequences=256*len(truth),
                                missing_fraction=miss/(256*len(truth)),expected=(1-p)**n)
                           for n,miss in missing.items())
        write_json('output/qualification/E2-discovery.json',summary)


class ExactnessE3(unittest.TestCase):
    def test_all_2187_fibers_with_independent_scalar_and_joint_oracle(self):
        model=industrial([row()]);compiled=Compiled(model);ids=model['signal_ids']
        full=[(bits,evaluate(model,dict(zip(ids,bits)))) for bits in product((False,True),repeat=7)]
        names=[k for k in compiled.roots if k not in ('R','R_minus_execution')]
        witnesses=0
        for values in product((None,False,True),repeat=7):
            model['observation_categories']=[dict(values=list(values),count=1)]
            reference=[v for bits,v in full if all(x is None or x==b for x,b in zip(values,bits))]
            actual=compiled.solve(witnesses=True)
            for name,estimate_ in actual['estimates'].items():
                self.assertEqual(estimate_['lower'],min(int(v[name]) for v in reference))
                self.assertEqual(estimate_['upper'],max(int(v[name]) for v in reference))
            expected={tuple(int(v[k]) for k in names) for v in reference}
            self.assertEqual(compiled.vectors(values,names),expected)
            witnesses+=verify_certificates(model,actual)['complete_witnesses']
        write_json('output/qualification/E3-exhaustive.json',dict(full_states=128,partial_observations=2187,
            joint_vectors_verified=True,complete_endpoint_witnesses=witnesses))

    def test_65_coordinates_and_more_than_ten_controls(self):
        model=industrial([row()])
        for i in range(58):
            key=f'zcompletion:{i:02d}';edge=f'extra:{i}'
            model['signal_ids'].append(key);model['completion_signals'].append(key)
            model['graph']['edges'].append(dict(id=edge,source='entry',target='service',type='sync',factors=[]))
            model['required_edge_completions'].append(dict(edge_id=edge,signal=key))
            model['observation_categories'][0]['values'].append(True)
        self.assertEqual(len(model['signal_ids']),65)
        for i in range(8):model['observation_categories'][0]['values'][i]=None
        self.check_exact(model)
        wide=industrial([row()]);wide['replicas']['entry']=[[]]
        for i in range(12):
            key=f'gate:{i:02d}';wide['replicas']['entry'][0].append(key)
            wide['signal_ids'].append(key);wide['observation_categories'][0]['values'].append(None if i<8 else True)
        self.check_exact(wide)

    def check_exact(self,model):
        ref=enumerate_model(model);actual=Compiled(model).solve(witnesses=True)
        self.assertEqual(actual['estimates'],ref['estimates']);verify_certificates(model,actual)

    def test_structural_diagnosis_and_physical_family(self):
        from fractions import Fraction
        cases=[(row(a=None,b=None,da=True,db=False),0,1),
               (row(a=True,call_completed=False),1,1)]
        for values,lo,hi in cases:
            answer=Compiled(industrial([values])).solve(['reachability_minus_execution'])['estimates']['reachability_minus_execution']
            self.assertEqual((answer['lower'],answer['upper']),(lo,hi))
        model=industrial([row(a=None,b=None,da=None,db=None,entry_completed=None,call_completed=True)])
        unconstrained=enumerate_model(model,['R'])['estimates']['R']
        constrained=enumerate_model(model,['R'],lambda s:not s['call_completed'] or s['entry_completed'])['estimates']['R']
        self.assertEqual((unconstrained['lower'],unconstrained['upper']),(0,1))
        self.assertEqual((constrained['lower'],constrained['upper']),(1,1))
        # Uniform completion assignments miss the nonmonotone target's maximum.
        self.assertEqual(max(int(a and not b) for a,b in ((False,False),(True,True))),0)
        self.assertEqual(max(int(a and not b) for a,b in product((False,True),repeat=2)),1)


class ReductionE4(unittest.TestCase):
    def model(self):
        graph=dict(services=['root','one','two'],edges=[
            dict(id='e1',source='root',target='one',type='sync',factors=[]),
            dict(id='e2',source='one',target='two',type='sync',factors=[])])
        proto=make_schema(graph,dict(root=[[]],one=[['K']],two=[[]]),
            dict(id='twenty',entry='root',required=['one','two'],semantics='immediate_sync_all_required'),[],
            [dict(edge_id='e1',signal='C1'),dict(edge_id='e2',signal='C2')])
        rows=[]
        for n,t,c1,c2,k in ((6,1,1,1,1),(4,1,1,None,1),(3,0,None,None,None),
                           (2,1,0,None,None),(3,1,1,1,None),(2,1,1,None,None)):
            rows.extend([dict(timely=bool(t),C1=None if c1 is None else bool(c1),
                C2=None if c2 is None else bool(c2),K=None if k is None else bool(k),entry_completed=True)]*n)
        return identify(proto,rows),rows

    def test_exact_law_three_paths_refinement_and_combination(self):
        model,rows=self.model();solved=Compiled(model).solve(witnesses=True);verify_certificates(model,solved)
        expected={'R':('9/20','3/4'),'execution':('3/10','3/4'),'R_minus_execution':('0','1/4')}
        for name,pair in expected.items():
            self.assertEqual(tuple(solved['estimates'][name][k] for k in ('lower_exact','upper_exact')),pair)
        full=query_full_r(model);projected=project_full(model);reduced=direct(rows,model['completion_signals'])
        self.assertEqual(projected,reduced);self.assertEqual(full,query_reduced(reduced))
        self.assertEqual(sorted(r['count'] for r in reduced['observation_categories']),[2,3,6,9])
        combination=Compiled(collapsed(model)).solve()
        self.assertEqual(combination['estimates'],Compiled(model).solve()['estimates'])
        disclosed=[dict(r,K=True) for r in rows]
        m=identify(model,disclosed);self.assertEqual(Compiled(m).solve()['estimates']['execution']['lower_exact'],'9/20')
        remaining=3;complete=[]
        for r in disclosed:
            r=dict(r)
            if r['C2'] is None and r['C1'] is True and r['timely']:
                r['C2']=remaining>0;remaining=max(0,remaining-1)
            for key in r:
                if r[key] is None:r[key]=False
            complete.append(r)
        final=query_full_r(identify(model,complete));self.assertEqual(final['lower_exact'],'3/5')
        self.assertEqual(final['lower'],final['upper'])
        write_json('output/qualification/E4-exact.json',dict(estimates=solved['estimates'],reduced=reduced,refined=final))


class StatisticalCounts(unittest.TestCase):
    def test_binomial_boundaries_and_discrepancy(self):
        self.assertEqual(lower(0,10,.025),0);self.assertEqual(upper(10,10,.025),1)
        self.assertAlmostEqual(upper(0,10,.025),1-.025**.1)
        self.assertAlmostEqual(lower(10,10,.025),.025**.1)
        prediction=dict(guaranteed=3,possible=7,samples=10,lower=.3,upper=.7)
        answer=forecast_metrics(prediction,8,10)
        self.assertIsNone(answer['signed_error']);self.assertAlmostEqual(answer['distance_to_frequency'],.1)
        self.assertLess(answer['discrepancy_outer95'][0],answer['discrepancy_outer95'][1])


if __name__=='__main__':unittest.main()
