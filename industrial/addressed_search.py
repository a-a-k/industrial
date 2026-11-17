"""Paired addressed allocation using the same exact cached production oracle."""
import argparse
import gzip
from itertools import combinations
import json
import math
import os
from pathlib import Path
import subprocess
import time
from .common import actions_only,read_json,write_json


class Budget(Exception):pass


class Oracle:
    def __init__(self,data,bank,analysis,root,cache_limit,deadline,target):
        self.deadline=deadline;self.target=target;self.root=Path(root);self.scores={};self.failed=set();self.last={}
        self.log=gzip.open(self.root/'queries.jsonl.gz','wt',encoding='utf-8')
        self.process=subprocess.Popen([str(Path('build/addressed-oracle').resolve()),data,bank,analysis,str(cache_limit)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        line=self.process.stdout.readline()
        if not line:raise ValueError('oracle preparation failed: '+self.process.stderr.read()[-1000:])
        self.meta=json.loads(line);self.used=self.meta['used'];self.n=self.meta['samples']
        write_json(self.root/'oracle.json',self.meta)
    def check(self):
        if time.perf_counter()>=self.deadline:raise Budget()
    def query(self,mask,full=True):
        self.check()
        if mask in self.scores:return self.scores[mask]
        self.process.stdin.write(json.dumps(dict(mask=mask,full=full,target=self.target))+'\n');self.process.stdin.flush()
        line=self.process.stdout.readline()
        if not line:raise ValueError('oracle query failed: '+self.process.stderr.read()[-1000:])
        answer=json.loads(line);self.last=answer;self.log.write(line);self.log.flush()
        for s,value in enumerate(answer['labels']):
            if value is False:self.failed.add((s,mask&self.meta['active_masks'][s]))
        if answer['complete']:self.scores[mask]=answer
        return answer
    def score(self,mask):return self.query(mask)['successes']
    def close(self):
        if self.process.poll() is None:
            try:self.process.stdin.write('{"stop":true}\n');self.process.stdin.flush()
            except BrokenPipeError:pass
            self.process.stdin.close();self.process.wait(timeout=10)
        self.log.close()
        if self.process.returncode:raise ValueError('oracle exited with an error')


def candidate(mask,score,target):
    return dict(mask=mask,machines=[m for m in range(32) if mask>>m&1],count=mask.bit_count(),
                training_successes=score,training_feasible=score>=target)


def choose(rows,target):
    valid=[r for r in rows if r['training_successes']>=target]
    return min(valid,key=lambda r:(r['count'],-r['training_successes'],r['mask'])) if valid else max(rows,key=lambda r:(r['training_successes'],-r['count'],-r['mask']))


def cheap(o,a,target,root):
    rows=[];controls={};uniform=o.meta['used_mask']
    def remember(mask):
        row=candidate(mask,o.score(mask),target);rows.append(row);return row
    base=remember(0);controls['none']=base;write_json(root/'checkpoint.json',dict(selected=base,controls=controls))
    if base['training_feasible']:
        controls.update({name:base for name in ('load','slack','greedy','pair')});return rows,controls
    controls['uniform']=remember(uniform)
    def save(name,row):
        controls[name]=row;write_json(root/'checkpoint.json',dict(selected=choose(rows,target),controls=controls))
    orders=dict(load=sorted(o.used,key=lambda m:(-a['machine_work'][m],m)),
        slack=sorted(o.used,key=lambda m:(min(a['deadline_slack'][i] for i in a['queues'][m]),m)))
    for name,order in orders.items():
        mask=0;selected=controls['uniform']
        for m in order:
            mask|=1<<m;selected=remember(mask)
            if selected['training_feasible']:break
        save(name,selected)
    def trim(mask):
        changed=True
        while changed:
            changed=False
            for m in o.used:
                if mask>>m&1:
                    trial=mask&~(1<<m)
                    if o.query(trial,False)['feasible']:mask=trial;changed=True
        return mask
    for name,pair in (('greedy',False),('pair',True)):
        mask=0
        while True:
            score=o.score(mask)
            if score>=target:mask=trim(mask);break
            left=[m for m in o.used if not mask>>m&1]
            if not left:break
            trials=[]
            for size in (1,2) if pair else (1,):
                for group in combinations(left,size):
                    trial=mask|sum(1<<m for m in group);value=o.score(trial)
                    trials.append(((value-score)/size,value,-size,-trial,trial))
            mask=max(trials)[-1]
        save(name,remember(mask))
    return rows,controls


def scan(o,best,target,root):
    limit=best['count'] if best['training_feasible'] else len(o.used)+1;visited=0
    for size in range(limit):
        for group in combinations(o.used,size):
            mask=sum(1<<m for m in group);answer=o.query(mask,False);visited+=1
            if answer['feasible']:
                selected=candidate(mask,o.score(mask),target)
                return selected,dict(status='TRAINING_MINIMUM_PROVED',minimum_proved=True,visited=visited)
    return best,dict(status='TRAINING_MINIMUM_PROVED' if best['training_feasible'] else 'TRAINING_INFEASIBLE',
                     minimum_proved=best['training_feasible'],visited=visited)


def lazy(o,best,target,root,seed):
    from ortools.sat.python import cp_model
    o.check();model=cp_model.CpModel();x={m:model.new_bool_var(f'repair-{m}') for m in o.used}
    z=[model.new_bool_var(f'success-{s}') for s in range(o.n)];model.add(sum(z)>=target);model.minimize(sum(x.values()))
    for s,row in enumerate(o.meta['bad']):
        for m in o.used:
            if row[m][0]:model.add(z[s]<=x[m])
            if row[m][1]:model.add(z[s]<=1-x[m])
    added=set();iterations=0;log=(root/'solver.jsonl').open('w',encoding='utf-8')
    def cuts():
        for s,pattern in sorted(o.failed-added):
            active=o.meta['active_masks'][s]
            difference=[1-x[m] if pattern>>m&1 else x[m] for m in o.used if active>>m&1]
            model.add(z[s]<=sum(difference));added.add((s,pattern))
    try:
        if best['training_feasible']:model.add(sum(x.values())<best['count'])
        while True:
            o.check();cuts();solver=cp_model.CpSolver();solver.parameters.num_search_workers=1
            solver.parameters.random_seed=seed;solver.parameters.max_time_in_seconds=max(.01,min(15,o.deadline-time.perf_counter()-.2))
            status=solver.solve(model);iterations+=1;name=solver.status_name(status)
            log.write(json.dumps(dict(iteration=iterations,status=name,cuts=len(added),wall_s=solver.WallTime()))+'\n');log.flush()
            if status==cp_model.INFEASIBLE:
                return best,dict(status='TRAINING_MINIMUM_PROVED' if best['training_feasible'] else 'TRAINING_INFEASIBLE',
                    minimum_proved=best['training_feasible'],iterations=iterations,cuts=len(added))
            if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
                return best,dict(status='CP_UNKNOWN',minimum_proved=False,iterations=iterations,cuts=len(added))
            mask=sum(1<<m for m in o.used if solver.boolean_value(x[m]));answer=o.query(mask,False)
            if answer['feasible']:
                best=candidate(mask,o.score(mask),target);write_json(root/'checkpoint.json',dict(selected=best))
                model.add(sum(x.values())<best['count'])
    finally:log.close()


def work(args):
    actions_only();started=time.perf_counter();root=Path(args.root);root.mkdir(parents=True,exist_ok=True)
    deadline=started+args.budget-1.5;a=read_json(args.analysis);o=Oracle(args.data,args.bank,args.analysis,root,args.cache_limit,deadline,args.target)
    rows=[];controls={};best=None;result={}
    try:
        rows,controls=cheap(o,a,args.target,root);best=choose(rows,args.target)
        write_json(root/'checkpoint.json',dict(selected=best,controls=controls))
        if best['training_feasible'] and best['count']==0:result=dict(status='TRAINING_MINIMUM_PROVED',minimum_proved=True)
        elif args.method=='lazy':best,result=lazy(o,best,args.target,root,args.seed)
        else:best,result=scan(o,best,args.target,root)
    except Budget:
        checkpoint=read_json(root/'checkpoint.json');best=checkpoint['selected'];controls=checkpoint.get('controls',controls)
        result=dict(status='BUDGET',minimum_proved=False)
    finally:o.close()
    if best is None:raise ValueError('no checked incumbent')
    memory={}
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmHWM:'):memory['VmHWM_bytes']=int(line.split()[1])*1024
    write_json(root/'answer.json',dict(status='PASS',method=args.method,selected=best,controls=controls,search=result,
        internal_wall_s=time.perf_counter()-started,budget_s=args.budget,oracle=o.last,
        incumbent_complete=all(k in controls for k in ('load','slack','greedy','pair')),**memory))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--bank',required=True);p.add_argument('--analysis',required=True)
    p.add_argument('--root',required=True);p.add_argument('--method',choices=['lazy','scan'],required=True);p.add_argument('--budget',type=float,default=120)
    p.add_argument('--target',type=int,default=500);p.add_argument('--cache-limit',type=int,default=1000000);p.add_argument('--seed',type=int,default=1907)
    work(p.parse_args())
