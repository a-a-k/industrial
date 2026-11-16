"""Frozen-plan diagnosis, bounded local correction and unopened external check."""
import argparse
import csv
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from fractions import Fraction
from .common import actions_only,canonical,digest,read_json,write_json
from .end_to_end import run
from .inputs import scenarios
from .local_corrections import catalogue,diff,earliest,materialize,structure
from .plan_campaign import paired_difference
from .production import check_physics,compare,outcomes,product_ledger,simulate
from .releases import fetch

ROOT=Path('output/fixed-local')
SOURCES=('industrial/fixed_plan_reinforcement.py','industrial/local_corrections.py',
    'industrial/inputs.py','industrial/production.py','industrial/statistics.py','industrial/targets.py',
    'engines/model.hpp','engines/risk_main.cpp','engines/des_ref/des.cpp','engines/dag_ref/dag.cpp',
    'engines/tsfg_op/operation_adapter.go','provenance/fixed_plan_reinforcement.json',
    'docs/FIXED_PLAN_REINFORCEMENT_RU.md')


def spec():return read_json('provenance/fixed_plan_reinforcement.json')
def fingerprint():return {p:digest(Path(p).read_bytes()) for p in SOURCES}
def stamp():return dict(commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
def plan_key(data):return digest(canonical(structure(data)))
def edit_key(e):return (e['cmax'],e['edit_count'],e['id'])


def compress_traces(root):
    for path in Path(root).rglob('*.jsonl'):
        with path.open('rb') as inp,gzip.open(str(path)+'.gz','wb') as out:shutil.copyfileobj(inp,out)
        path.unlink()


def build():
    ROOT.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    Path('build').mkdir(exist_ok=True)
    common=float((ROOT/'preparation-common-end.txt').read_text())-float((ROOT/'preparation-start.txt').read_text())
    go=float((ROOT/'preparation-go-end.txt').read_text())-float((ROOT/'preparation-go-start.txt').read_text())
    command=['g++','-std=c++20','-O3','-DNDEBUG','-Wall','-Wextra','-Werror','-Ivendor',
             'engines/risk_main.cpp','-o','build/risk-dag']
    subprocess.run(command,check=True)
    scalar=time.perf_counter()-started
    public=run([sys.executable,'scripts/build.py'],env={**os.environ,'PUBLIC_ONLY':'1'})
    source=run([sys.executable,'scripts/fetch_tsfg.py'])
    t=time.perf_counter();preflight,_=fetch(spec()['preflight'],'output/local-build-preflight');evidence_s=time.perf_counter()-t
    s1=run([sys.executable,'scripts/build.py'],env={**os.environ,'S1_ONLY':'1',
        'TSFG_TEST_EVIDENCE':str(preflight/'provenance/tsfg-provenance.json')})
    write_json(ROOT/'preparation.json',dict(common_environment_s=common,go_setup_s=go,scalar_compile_s=scalar,
        public_compile=public,s1_source=source,s1_compile=s1,preflight_evidence_retrieval_s=evidence_s,
        participant_first_use_s=dict(D=common+go+source['wall_s']+evidence_s+s1['wall_s'],
            DAG=common+scalar+public['wall_s']),
        compiler_command=command,scalar_sha256=digest(Path('build/risk-dag').read_bytes()),**stamp()))
    if any(p['status']!='OK' for p in (public,source,s1)):raise ValueError('participant preparation failed')


def input_plan(registry,instance):
    source,receipt=fetch(registry['input_seal'],'output/local-input-seal');seal=read_json(source/'seal.json')
    if seal['status']!='SEALED' or {r['instance'] for r in seal['inputs']}!=set(spec()['instances']):
        raise ValueError('all ten fixed nominal inputs must be sealed')
    entry=next(r for r in seal['inputs'] if r['instance']==instance);data=read_json(source/instance/'schedule.json')
    if digest(canonical(data))!=entry['schedule_sha256']:raise ValueError('fixed input changed')
    return data,dict(release=registry['input_seal'],receipt=receipt,input=entry)


def baseline(data,histories,root,engine,deadline):
    horizon=data['nominal_makespan']*5//4
    rows,processes=simulate(data,histories,root,engine,horizon)
    write_json(Path(root)/'processes.json',processes)
    if len(rows)!=len(histories) or any(p['status']!='OK' for p in processes):raise ValueError('baseline trace unavailable')
    labels=outcomes(product_ledger(data,histories,rows),[j['id'] for j in data['jobs']],deadline)
    if any(v is None for v in labels.values()):raise ValueError('baseline outcome unavailable')
    ops=data['operations'];previous={b:a for q in data['queues'] for a,b in zip(q,q[1:])}
    machine=[0]*len(data['queues']);operation=[0]*len(ops);example=None
    for scenario in histories:
        row=rows[scenario['id']];check_physics(data,scenario,row)
        if labels[scenario['id']]:continue
        down=[[] for _ in data['queues']]
        for m,a,b in scenario['failures']:down[m].append((a,b))
        parts=[]
        def finish(i):return min(deadline,row['finish'][i]) if row['finish'][i] is not None else deadline
        for o in ops:
            i=o['id'];planned=min(deadline,o['planned_start'])
            ready=min(deadline,max([o['release'],o['planned_start'],*[finish(p) for p in o['predecessors']]]))
            eligible=max(ready,finish(previous[i]) if i in previous else 0)
            started=row['start'][i] is not None and row['start'][i]<=deadline
            start=row['start'][i] if started else deadline;end=finish(i) if started else deadline
            pause=sum(max(0,min(end,b)-max(start,a)) for a,b in down[o['machine']]) if started else 0
            repair=start-eligible;served=end-start-pause if started else 0
            p=dict(operation=i,job=o['job'],machine=o['machine'],upstream_wait=ready-planned,
                machine_queue_wait=eligible-ready,repair_wait=repair,processing_pause=pause,
                started=started,complete=row['finish'][i] is not None and row['finish'][i]<=deadline)
            if min(p[k] for k in ('upstream_wait','machine_queue_wait','repair_wait','processing_pause'))<0:
                raise ValueError('negative diagnostic delay')
            if sum(p[k] for k in ('upstream_wait','machine_queue_wait','repair_wait','processing_pause'))!=end-planned-served:
                raise ValueError('delay accounting overlap')
            if repair!=sum(max(0,min(start,b)-max(eligible,a)) for a,b in down[o['machine']]):
                raise ValueError('post-eligibility waiting not explained by availability')
            machine[o['machine']]+=repair+pause;operation[i]+=repair+pause;parts.append(p)
        if example is None:
            late=next(j for j in data['jobs'] if row['finish'][j['final_operation']] is None or row['finish'][j['final_operation']]>deadline)
            pending=[late['final_operation']];seen=set();links=[]
            while pending:
                i=pending.pop()
                if i in seen:continue
                seen.add(i);p=parts[i];o=ops[i]
                if p['upstream_wait'] and o['predecessors']:
                    latest=max(finish(k) for k in o['predecessors'])
                    for k in o['predecessors']:
                        if finish(k)==latest:links.append(dict(source=k,target=i,kind='technology'));pending.append(k)
                if p['machine_queue_wait'] and i in previous:
                    k=previous[i];links.append(dict(source=k,target=i,kind='machine_queue'));pending.append(k)
            example=dict(attempt=scenario['id'],late_job=late['id'],parts=[parts[i] for i in sorted(seen)],links=links)
    report=dict(samples=len(histories),successes=sum(labels.values()),failed=len(histories)-sum(labels.values()),
        machine_direct=machine,operation_direct=operation,example=example,
        units='ticks summed over operations in failed batches; not batch-duration losses',
        interpretation='observed delays; no causal attribution to feasible corrections')
    write_json(Path(root)/'diagnosis.json',report);compress_traces(root)
    return labels,report


class Scorer:
    def __init__(self,root,data,deadline,engine):
        self.root=Path(root);self.data=data;self.deadline=deadline;self.engine=engine;self.calls=[]
        self.history_path=self.root/'current-scenarios.json';self.plan_path=self.root/'current-plan.json'
    def evaluate(self,plan,histories,label):
        if not histories:return []
        write_json(self.history_path,histories);write_json(self.plan_path,plan)
        target=self.root/'native'/f'{len(self.calls):05d}.json';target.parent.mkdir(exist_ok=True)
        env={**os.environ,'GOMAXPROCS':'1','RISK_TRACE':'1'}
        if self.engine=='tsfg':
            env.update(TSFG_OP_DRIVER='true',TSFG_OUTPUT_PROFILE='RISK-ONLY')
            command=[str(Path('.private/runtime/tsfg').resolve()),'tsfg',str(self.plan_path),str(self.history_path),
                     str(target),'MISSION',str(self.deadline),'5']
        else:command=[str(Path('build/risk-dag').resolve()),str(self.plan_path),str(self.history_path),str(target),str(self.deadline)]
        process=run(command,spec()['process_watchdog_s'],env)
        record=dict(label=label,samples=len(histories),scenario_sha256=digest(canonical(histories)),
            plan_sha256=digest(canonical(plan)),process=process)
        self.calls.append(record)
        write_json(self.root/'calls.json',self.calls)
        if process['status']!='OK' or not target.exists():raise ValueError('candidate evaluation unavailable')
        result=read_json(target);times=result['finished_at']
        if len(times)!=len(histories) or result['sample_count']!=len(histories):raise ValueError('candidate census')
        labels=[t is not None and t<=self.deadline for t in times]
        if sum(labels)!=result['finished_count']:raise ValueError('scalar success mismatch')
        if self.engine=='tsfg':
            from .targets import query_reduced
            k=sum(labels);n=len(labels);categories=[]
            if k:categories.append(dict(values=[True,True],count=k))
            if k<n:categories.append(dict(values=[False,None],count=n-k))
            q=query_reduced(dict(signal_ids=['timely','__logical_completions__'],sample_count=n,observation_categories=categories))
            if q['guaranteed']!=k or q['possible']!=k:raise ValueError('SIMPAT full-observation count mismatch')
        return labels


def worker(input_path,law,method,folder):
    import resource
    started=time.perf_counter();cfg=spec();root=Path(folder);root.mkdir(parents=True,exist_ok=True)
    data=read_json(input_path);deadline=data['nominal_makespan']*11//10;phases={}
    t=time.perf_counter();edits,catstats=catalogue(data);phases['catalogue_s']=time.perf_counter()-t
    write_json(root/'catalogue.json',dict(edits=edits,stats=catstats))
    t=time.perf_counter();histories=scenarios(data,law,cfg['calibration_split'],cfg['calibration_samples'])
    write_json(root/'scenarios.json.gz',histories);phases['scenario_generation_s']=time.perf_counter()-t
    engine='tsfg' if method=='D' else 'dag'
    t=time.perf_counter();original,diagnosis=baseline(data,histories,root/'baseline',engine,deadline)
    phases['baseline_trace_diagnosis_s']=time.perf_counter()-t
    scores={'none':sum(original.values())};scorer=Scorer(root,data,deadline,engine);sensitivity=[]
    t=time.perf_counter();nonempty=[e for e in edits if e['kind']!='none'];byid={e['id']:e for e in edits}
    if method in ('D','D-DAG'):
        failed=[s for s in histories if not original[s['id']]]
        for m in range(len(data['queues'])):
            relevant=[s for s in failed if any(k==m and a<deadline and b>0 for k,a,b in s['failures'])]
            changed=[dict(s,failures=[f for f in s['failures'] if f[0]!=m]) for s in relevant]
            rescued=sum(scorer.evaluate(data,changed,f'perfect-availability-{m}'))
            sensitivity.append(dict(machine=m,rescued_failed=rescued,evaluated=len(changed),
                skipped_successful=len(histories)-len(failed),skipped_failed_without_prior_outage=len(failed)-len(relevant)))
        top=[r['machine'] for r in sorted(sensitivity,key=lambda r:(-r['rescued_failed'],r['machine']))[:2]]
        order=sorted([e for e in nonempty if set(e['machines'])&set(top)],key=edit_key)
    elif method=='N':order=[]
    elif method=='L':order=sorted(edits,key=edit_key)[:1]
    elif method=='S':
        load=[sum(data['operations'][i]['work'] for i in q) for q in data['queues']]
        order=sorted(nonempty,key=lambda e:(-max(Fraction(load[m],data['planned_makespan']) for m in e['machines']),
            min(catstats['base_slack'][i] for i in e['operations']),e['cmax'],e['id']))
    elif method=='T':
        ms,ops=diagnosis['machine_direct'],diagnosis['operation_direct'];sm,so=sum(ms),sum(ops)
        def trace_score(e):
            return (Fraction(sum(ms[m] for m in e['machines']),sm) if sm else Fraction(0))+(
                Fraction(sum(ops[i] for i in e['operations']),so) if so else Fraction(0))
        order=sorted(nonempty,key=lambda e:(-trace_score(e),e['cmax'],e['id']))
    elif method=='G':
        screening=[]
        for e in sorted(edits,key=edit_key):
            count=sum(list(original.values())[:cfg['screen_samples']]) if e['kind']=='none' else sum(
                scorer.evaluate(materialize(data,e),histories[:cfg['screen_samples']],'screen:'+e['id']))
            screening.append(dict(edit=e['id'],successes=count))
        write_json(root/'screening.json',screening);screen={r['edit']:r['successes'] for r in screening}
        order=sorted(nonempty,key=lambda e:(-screen[e['id']],e['edit_count'],e['cmax'],e['id']))
    else:raise ValueError('unregistered method')
    considered=[e for e in order if e['kind']!='none'][:cfg['candidate_quota']-1]
    for e in considered:scores[e['id']]=sum(scorer.evaluate(materialize(data,e),histories,'full:'+e['id']))
    selected=min((byid[k] for k in scores),key=lambda e:(-scores[e['id']],e['edit_count'],e['cmax'],e['id']))
    if method=='L':
        # Nominal-only control does not let noisy risk observations override its rule.
        selected=min(edits,key=edit_key)
        if selected['id'] not in scores:scores[selected['id']]=sum(scorer.evaluate(materialize(data,selected),histories,'nominal-selected'))
    phases['diagnostic_probes_screening_candidate_selection_s']=time.perf_counter()-t
    plan=materialize(data,selected);write_json(root/'schedule.json',plan);write_json(root/'diff.json',diff(data,plan))
    answer=dict(status='PASS',method=method,law=law,instance=data['dataset_id'],selected=selected,
        calibration_successes=scores[selected['id']],baseline_successes=scores['none'],samples=len(histories),
        scores=scores,sensitivity=sensitivity,diagnosis=diagnosis,catalogue_sha256=digest(canonical(edits)),
        scenario_sha256=digest(canonical(histories)),schedule_sha256=digest(canonical(plan)),
        phases=phases,internal_wall_s=time.perf_counter()-started,
        native_calls=len(scorer.calls),catalogue_stats=catstats,implementation=fingerprint(),spec=cfg)
    usage=resource.getrusage(resource.RUSAGE_SELF);children=resource.getrusage(resource.RUSAGE_CHILDREN)
    answer.update(cpu_s=usage.ru_utime+usage.ru_stime+children.ru_utime+children.ru_stime,
        worker_ru_maxrss_kib=usage.ru_maxrss,children_ru_maxrss_kib=children.ru_maxrss,
        memory_scope='individual process peaks; not simultaneous process-tree memory')
    write_json(root/'answer.json',answer)
    for name in ('current-plan.json','current-scenarios.json'):
        if (root/name).exists():(root/name).unlink()


def qualify(registry):
    from tests.test_planning import problem
    ROOT.mkdir(parents=True,exist_ok=True);checks=[];tiny=problem()
    tiny['planned_makespan']=max(o['planned_end'] for o in tiny['operations']);tiny['nominal_makespan']=100
    edits,stats=catalogue(tiny)
    if not any(e['kind']=='move' for e in edits):raise ValueError('qualification missing physical reroute')
    for index,e in enumerate(edits):
        plan=materialize(tiny,e);qs=plan['queues']
        if e['kind']=='move':
            i=e['operation']
            if [[x for x in q if x!=i] for q in qs]!=[[x for x in q if x!=i] for q in tiny['queues']]:
                raise ValueError('reroute changed another operation order')
        check_case(tiny,plan,e,f'tiny-{index}',checks)
    base,provenance=input_plan(registry,'Mk10');edits,stats=catalogue(base)
    chosen=[edits[0]]
    for kind in ('swap','move'):
        found=[e for e in edits if e['kind']==kind]
        if found:chosen.extend([found[0],found[len(found)//2],found[-1]])
    for index,e in enumerate({e['id']:e for e in chosen}.values()):check_case(base,materialize(base,e),e,f'Mk10-{index}',checks)
    write_json(ROOT/'qualification.json',dict(status='PASS',checks=checks,catalogue_stats=stats,
        input_provenance=provenance,implementation=fingerprint(),spec=spec(),**stamp()))


def check_case(base,plan,edit,label,checks):
    root=ROOT/'checks'/label;deadline=base['nominal_makespan']*11//10
    histories=scenarios(base,'F1','fixed-local-v1-qualification',16)
    histories.extend([dict(id=label+'-healthy',failures=[],work_overrides=[]),
        dict(id=label+'-blocked',failures=[[0,0,2*deadline]],work_overrides=[])])
    rows={};labels={}
    for engine in ('des','dag','tsfg'):
        out,ps=simulate(plan,histories,root/engine,engine,deadline)
        if len(out)!=len(histories) or any(p['status']!='OK' for p in ps):raise ValueError('qualification engine unavailable')
        for s in histories:check_physics(plan,s,out[s['id']])
        rows[engine]=out;labels[engine]=outcomes(product_ledger(plan,histories,out),[j['id'] for j in plan['jobs']],deadline)
    for s in histories:
        compare(rows['des'][s['id']],rows['dag'][s['id']]);compare(rows['des'][s['id']],rows['tsfg'][s['id']])
    for engine in ('dag','tsfg'):
        scorer=Scorer(root/('scalar-'+engine),plan,deadline,engine);scorer.root.mkdir(parents=True)
        actual=scorer.evaluate(plan,histories,'qualification')
        if actual!=list(labels['des'].values()):raise ValueError('scalar vs independent product ledger')
    checks.append(dict(case=label,edit=edit,samples=len(histories),status='PASS'))
    compress_traces(root)


def train(registry,instance,law):
    ROOT.mkdir(parents=True,exist_ok=True);data,provenance=input_plan(registry,instance)
    qsource,qreceipt=fetch(registry['qualification'],'output/local-qualification')
    q=read_json(qsource/'qualification.json')
    if q['status']!='PASS' or q['implementation']!=fingerprint() or q['spec']!=spec():raise ValueError('unqualified implementation')
    write_json(ROOT/'input.json',data);records=[];answers={}
    for method in spec()['methods']:
        folder=ROOT/method
        process=run([sys.executable,'-m','industrial.fixed_plan_reinforcement','worker',
            '--input',str(ROOT/'input.json'),'--law',law,'--method',method,'--folder',str(folder)],spec()['process_watchdog_s'])
        record=dict(method=method,process=process);records.append(record);write_json(ROOT/'progress.json',records)
        if process['status']=='OK' and (folder/'answer.json').exists():answers[method]=read_json(folder/'answer.json')
    status='PASS' if len(answers)==len(spec()['methods']) else 'PARTIAL'
    if status=='PASS':
        left,right=answers['D'],answers['D-DAG']
        for key in ('selected','scores','sensitivity','catalogue_sha256','scenario_sha256','schedule_sha256','diagnosis'):
            if left[key]!=right[key]:raise ValueError('identical diagnostic policy engine mismatch: '+key)
        if len({a['catalogue_sha256'] for a in answers.values()})!=1 or len({a['scenario_sha256'] for a in answers.values()})!=1:
            raise ValueError('method information asymmetry')
    write_json(ROOT/'training.json',dict(status=status,instance=instance,law=law,input_provenance=provenance,
        qualification_receipt=qreceipt,answers=answers,records=records,preparation=read_json(ROOT/'preparation.json'),
        implementation=fingerprint(),spec=spec(),**stamp()))
    if status!='PASS':raise ValueError('all methods must finish before holdout can open')


def seal(registry):
    cfg=spec();ROOT.mkdir(parents=True,exist_ok=True);records=[];seen=set();input_tags=set()
    expected={(i,l) for i in cfg['instances'] for l in cfg['laws']}
    for index,tag in enumerate(registry['trainings']):
        source,receipt=fetch(tag,f'output/local-training-{index}');record=read_json(source/'training.json')
        key=(record['instance'],record['law'])
        if record['status']!='PASS' or record['implementation']!=fingerprint() or record['spec']!=cfg or key in seen:
            raise ValueError('unavailable, changed or duplicate training')
        if set(record['answers'])!=set(cfg['methods']):raise ValueError('control missing')
        seen.add(key);input_tags.add(record['input_provenance']['release']);cell=key[0]+'-'+key[1]
        dest=ROOT/cell;dest.mkdir();shutil.copyfile(source/'input.json',dest/'input.json')
        for method,answer in record['answers'].items():
            plan=read_json(source/method/'schedule.json')
            if digest(canonical(plan))!=answer['schedule_sha256']:raise ValueError('selected correction changed')
            write_json(dest/(method+'.json'),plan)
            shutil.copyfile(source/method/'diff.json',dest/(method+'-diff.json'))
        records.append(dict(training_release=tag,training_receipt=receipt,**record))
    if seen!=expected or len(input_tags)!=1:raise ValueError('all 20 conditions and one common input seal required')
    write_json(ROOT/'seal.json',dict(status='SEALED',conditions=records,implementation=fingerprint(),spec=cfg,
        holdout_generated=False,paired_family=dict(comparisons=100,one_sided_alpha=.000125),**stamp()))


def validate(registry,instance,law):
    started=time.perf_counter();cfg=spec();ROOT.mkdir(parents=True,exist_ok=True)
    source,receipt=fetch(registry['seal'],'output/local-all-decisions');sealed=read_json(source/'seal.json')
    expected={(i,l) for i in cfg['instances'] for l in cfg['laws']}
    if sealed['status']!='SEALED' or sealed['spec']!=cfg or sealed['implementation']!=fingerprint():
        raise ValueError('unavailable global pre-holdout seal')
    if {(r['instance'],r['law']) for r in sealed['conditions']}!=expected:raise ValueError('partial seal cannot open holdout')
    record=next(r for r in sealed['conditions'] if r['instance']==instance and r['law']==law)
    cell=instance+'-'+law;base=read_json(source/cell/'input.json');deadline=base['nominal_makespan']*11//10
    histories=scenarios(base,law,cfg['validation_split'],cfg['validation_samples'])
    if digest(canonical(histories)) in {a['scenario_sha256'] for a in record['answers'].values()}:
        raise ValueError('calibration and validation histories overlap')
    write_json(ROOT/'scenarios.json.gz',histories);write_json(ROOT/'input.json',base)
    plans={};aliases={}
    for method in cfg['methods']:
        plan=read_json(source/cell/(method+'.json'));answer=record['answers'][method]
        if digest(canonical(plan))!=answer['schedule_sha256']:raise ValueError('sealed plan hash changed')
        rebuilt=materialize(base,answer['selected'])
        if canonical(rebuilt)!=canonical(plan):raise ValueError('plan differs from the one registered small edit')
        key=plan_key(plan);plans.setdefault(key,plan);aliases[method]=key
    labels={};checks=[]
    for index,(key,plan) in enumerate(plans.items()):
        root=ROOT/'plans'/key;root.mkdir(parents=True);write_json(root/'schedule.json',plan);write_json(root/'diff.json',diff(base,plan))
        trajectories={}
        for engine in ('des','dag'):
            rows,ps=simulate(plan,histories,root/engine,engine,base['nominal_makespan']*5//4)
            write_json(root/(engine+'-processes.json'),ps)
            if len(rows)!=len(histories) or any(p['status']!='OK' for p in ps):raise ValueError('external validation incomplete')
            trajectories[engine]=rows
        for s in histories:
            for engine in ('des','dag'):check_physics(plan,s,trajectories[engine][s['id']])
            compare(trajectories['des'][s['id']],trajectories['dag'][s['id']])
        external=outcomes(product_ledger(plan,histories,trajectories['des']),[j['id'] for j in plan['jobs']],deadline)
        if any(v is None for v in external.values()):raise ValueError('external product census unavailable')
        scalar_root=root/'s1-scalar';scalar_root.mkdir()
        scalar=Scorer(scalar_root,plan,deadline,'tsfg').evaluate(plan,histories,'sealed-independent-validation')
        if scalar!=list(external.values()):raise ValueError('S1 risk vs external product result mismatch')
        sample=histories[:cfg['full_tsfg_check_samples']]
        s1,ps=simulate(plan,sample,root/'s1-full','tsfg',base['nominal_makespan']*5//4)
        write_json(root/'s1-full-processes.json',ps)
        if len(s1)!=len(sample) or any(p['status']!='OK' for p in ps):raise ValueError('full S1 trace check unavailable')
        for s in sample:
            check_physics(plan,s,s1[s['id']]);compare(s1[s['id']],trajectories['des'][s['id']])
        labels[key]=external;write_json(root/'external-labels.json.gz',external)
        checks.append(dict(plan=key,samples=len(histories),successes=sum(external.values()),des_dag_physics_and_trace_mismatches=0,
            s1_scalar_samples=len(histories),s1_full_trace_samples=len(sample)))
        del trajectories;compress_traces(root)
        for path in root.rglob('*-input.json'):path.unlink()
        write_json(ROOT/'progress.json',dict(completed=checks,planned_unique=len(plans)))
    answers={m:labels[k] for m,k in aliases.items()};contrasts={}
    for baseline_method in ('N','L','S','T','G'):
        contrasts[baseline_method]=paired_difference(answers['D'],answers[baseline_method],cfg['paired_bound_alpha'])
    from .statistics import outer
    method_results={m:dict(plan=aliases[m],successes=sum(answers[m].values()),samples=len(histories),
        probability=sum(answers[m].values())/len(histories),ci95=outer(sum(answers[m].values()),sum(answers[m].values()),len(histories)))
        for m in cfg['methods']}
    write_json(ROOT/'validation.json',dict(status='PASS',instance=instance,law=law,seal_release=registry['seal'],
        seal_receipt=receipt,training=record,deadline=deadline,unique_plans=len(plans),methods=method_results,
        paired_D_against=contrasts,checks=checks,scenario_sha256=digest(canonical(histories)),
        validation_wall_s=time.perf_counter()-started,spec=cfg,implementation=fingerprint(),**stamp()))


def report(registry):
    cfg=spec();ROOT.mkdir(parents=True,exist_ok=True);records=[];seen=set();missing=[]
    expected={(i,l) for i in cfg['instances'] for l in cfg['laws']}
    for index,tag in enumerate(registry.get('validations',[])):
        try:
            source,receipt=fetch(tag,f'output/local-validation-{index}');r=read_json(source/'validation.json')
            key=(r['instance'],r['law'])
            if r['status']!='PASS' or r['implementation']!=fingerprint() or r['spec']!=cfg or key in seen:
                raise ValueError('incomplete or changed validation')
            seen.add(key);records.append(dict(validation_release=tag,validation_receipt=receipt,**r))
        except Exception as error:missing.append(dict(release=tag,error=str(error)))
    missing.extend(dict(instance=i,law=l,error='required acceptance condition unavailable') for i,l in sorted(expected-seen))
    rows=[];costs=[];practical=[];comparative=[]
    for r in sorted(records,key=lambda r:(r['instance'],r['law'])):
        processes={p['method']:p['process'] for p in r['training']['records']}
        for method,answer in r['methods'].items():
            training=r['training']['answers'][method];p=processes[method]
            costs.append(dict(instance=r['instance'],law=r['law'],method=method,complete_process_wall_s=p['wall_s'],
                first_use_wall_s=p['wall_s']+r['training']['preparation']['participant_first_use_s']['D' if method=='D' else 'DAG'],
                cpu_s=training['cpu_s'],catalogue_s=training['phases']['catalogue_s'],native_calls=training['native_calls'],
                worker_ru_maxrss_kib=training['worker_ru_maxrss_kib'],children_ru_maxrss_kib=training['children_ru_maxrss_kib']))
        d,n=r['methods']['D'],r['methods']['N'];effect=r['paired_D_against']['N']
        rows.append(dict(instance=r['instance'],law=r['law'],baseline_successes=n['successes'],
            corrected_successes=d['successes'],samples=d['samples'],difference=effect['difference'],
            familywise_lo=effect['outer95'][0],familywise_hi=effect['outer95'][1],
            edit=r['training']['answers']['D']['selected']['id'],D_wall_s=processes['D']['wall_s'],
            D_DAG_wall_s=processes['D-DAG']['wall_s'],G_wall_s=processes['G']['wall_s']))
        if effect['outer95'][0]>0:practical.append(dict(instance=r['instance'],law=r['law'],contrast=effect))
        for b in ('L','S','T','G'):
            contrast=r['paired_D_against'][b]
            for implementation in ('D','D-DAG'):
                same=r['methods'][b]['plan']==d['plan'];cheaper=processes[implementation]['wall_s']<processes[b]['wall_s']
                better=contrast['outer95'][0]>0 and processes[implementation]['wall_s']<=1.25*processes[b]['wall_s']
                if better or (same and cheaper):comparative.append(dict(instance=r['instance'],law=r['law'],implementation=implementation,
                    baseline=b,reason='better external outcome within 1.25x complete measured effort' if better else 'identical physical plan at lower complete measured effort'))
    for name,values in (('summary.csv',rows),('costs.csv',costs)):
        if values:
            with (ROOT/name).open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(values[0]));writer.writeheader();writer.writerows(values)
    result=dict(status='COMPLETE' if not missing and seen==expected else 'PARTIAL',conditions=records,
        completed_conditions=len(seen),required_conditions=20,missing=missing,summary=rows,costs=costs,
        confirmed_practical_conditions=practical,measured_comparative_pairs=comparative,
        scope='synthetic fixed-plan crash tests; no real-plant validation and no commercial-product measurements',
        confidence_family='100 paired differences; four one-sided CP bounds each alpha=.000125',
        cost_limit='one measured full process per method/condition; observed cost ordering, not a repeated timing speed theorem',
        implementation=fingerprint(),spec=cfg,**stamp())
    write_json(ROOT/'RESULT.json',result)
    lines=['# Краш-тесты фиксированных планов Mk01–Mk10','',f'Полнота серии: **{result["status"]}**, условий {len(seen)}/20.',
        '',f'Подтверждённый рост вероятности выпуска относительно исходного плана: {len(practical)} условий с общей 95%-й гарантией для семейства 100 сравнений.',
        'Завершение кампании, полезность конкретной правки и преимущество диагностической стратегии — отдельные результаты.',
        '', '| Задача | Закон | Исходный план | Правка D | Изменение, п.п. | Общая внешняя граница, п.п. | Правка |',
        '|---|---|---:|---:|---:|---:|---|']
    for r in rows:lines.append(f'| {r["instance"]} | {r["law"]} | {r["baseline_successes"]}/{r["samples"]} | '
        f'{r["corrected_successes"]}/{r["samples"]} | {100*r["difference"]:.2f} | '
        f'[{100*r["familywise_lo"]:.2f}; {100*r["familywise_hi"]:.2f}] | {r["edit"]} |')
    lines+=['', 'Все методы стартуют с одного замороженного CP-плана. Машины, совместимость, партия и прежний срок одинаковы. Исправление меняет не более одной очередной пары либо одного назначения; все последствия для времён раскрыты.',
        'Решения всех 20 условий были зафиксированы до создания новых проверочных сценариев. Единица испытания — целая партия. Измеренные частоты и все контроли сохранены в RESULT.json.',
        'Идеальная доступность применялась только для диагностики. Выпуск проверен независимым DES; DAG и исходный S1 проверяли согласованность. Описательная цепочка задержек не выдаётся за эффект реального исправления.',
        'D и D-DAG реализуют одинаковую стратегию и должны совпадать. Это позволяет отдельно оценивать стратегию и стоимость S1. При полных наблюдениях SIMPAT не добавляет информацию к частоте виртуальных успехов.',
        'В costs.csv указаны полные измеренные процессы, включая построение каталога, сценарии, трассы, вмешательства, оценку всех рассмотренных правок и запись ответа. Первичная установка и сборка, историческое построение исходных планов и независимая проверка раскрыты в первичных выпусках отдельно.',
        'Один замер на условие не подтверждает устойчивое ускорение. Совпадение доверительных интервалов не означает эквивалентность методов. Совпадение физического плана устанавливается по точным назначениям и очередям.',
        'Коммерческие продукты не запускались. Открытые контроли не являются измерениями BFG, Adeptik, ALINA или Simio.']
    if missing:lines+=['',f'Невыполненных обязательств: {len(missing)}. Они не заменяются квалификацией Mk10 или завершёнными подмножествами.']
    (ROOT/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    if result['status']!='COMPLETE':raise ValueError('full 20-condition acceptance remains incomplete')


def main():
    actions_only();p=argparse.ArgumentParser();p.add_argument('stage');p.add_argument('--registry',default='{}')
    p.add_argument('--instance');p.add_argument('--law');p.add_argument('--method');p.add_argument('--input');p.add_argument('--folder')
    args=p.parse_args();registry=json.loads(args.registry)
    if args.stage=='build':build()
    elif args.stage=='qualify':qualify(registry)
    elif args.stage=='worker':worker(args.input,args.law,args.method,args.folder)
    elif args.stage=='train':train(registry,args.instance,args.law)
    elif args.stage=='seal':seal(registry)
    elif args.stage=='validate':validate(registry,args.instance,args.law)
    elif args.stage=='report':report(registry)
    else:raise ValueError('unregistered stage')


if __name__=='__main__':main()
