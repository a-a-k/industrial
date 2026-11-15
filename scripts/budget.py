"""Reserve unfinished job limits against the complete 72 runner-hour campaign."""
import datetime as dt
import json
import os
from pathlib import Path
import urllib.request

if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
repo=os.environ['GITHUB_REPOSITORY'];token=os.environ['GH_TOKEN']
def get(path):
    request=urllib.request.Request('https://api.github.com/'+path,headers={
        'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(request,timeout=60) as r:return json.load(r)
def when(s):return dt.datetime.fromisoformat(s.replace('Z','+00:00'))
completed=0.;reserved=0.;census=[]
page=1
while True:
    runs=get(f'repos/{repo}/actions/runs?per_page=100&page={page}')['workflow_runs']
    if not runs:break
    for run in runs:
        jp=1
        while True:
            jobs=get(f'repos/{repo}/actions/runs/{run["id"]}/jobs?filter=all&per_page=100&page={jp}')['jobs']
            if not jobs:break
            for job in jobs:
                elapsed=0.
                if job['status']=='completed' and job.get('started_at') and job.get('completed_at'):
                    elapsed=max(0.,(when(job['completed_at'])-when(job['started_at'])).total_seconds());completed+=elapsed
                elif job['status']!='completed':reserved+=90*60
                census.append(dict(id=job['id'],run=run['id'],status=job['status'],elapsed_s=elapsed))
            if len(jobs)<100:break
            jp+=1
    if len(runs)<100:break
    page+=1
report=dict(limit_s=72*3600,completed_s=completed,reserved_s=reserved,jobs=census,
            monetary_budget=0,runner_policy='public standard ubuntu-24.04 only')
report['reserved_final_report_s']=90*60
report['dispatch_limit_s']=72*3600 if os.environ.get('FINAL_REPORT')=='1' else 72*3600-90*60
Path('output').mkdir(exist_ok=True);Path('output/budget.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='jobs'}))
if completed+reserved>report['dispatch_limit_s']:raise SystemExit('Campaign budget reservation exceeded; remaining obligations are PARTIAL')
