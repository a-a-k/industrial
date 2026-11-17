"""Reserve unfinished job limits against the complete 72 runner-hour campaign."""
import datetime as dt
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
repo=os.environ['GITHUB_REPOSITORY'];token=os.environ['GH_TOKEN']
def get(path):
    request=urllib.request.Request('https://api.github.com/'+path,headers={
        'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request,timeout=60) as r:return json.load(r)
        except (urllib.error.URLError,TimeoutError) as error:
            code=error.code if isinstance(error,urllib.error.HTTPError) else None
            transient=code is None or code==429 or 500<=code<600
            final=not transient or attempt==4
            delay=0 if final else min(30,2**(attempt+1))
            retries.append(dict(path=path,attempt=attempt+1,http_status=code,final=final,retry_delay_s=delay))
            Path('output').mkdir(exist_ok=True)
            Path('output/budget-api-retries.json').write_text(json.dumps(retries,indent=2)+'\n')
            print(json.dumps(dict(budget_api_http_status=code,attempt=attempt+1,retrying=not final)))
            if final:raise
            time.sleep(delay)

retries=[]
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
                job_limit_s=270*60 if run.get('path','').split('@')[0].endswith('/measure-extended.yml') and job['name']!='report' else 90*60
                if run.get('path','').split('@')[0].endswith('/addressed-repair.yml') and job['name'].startswith(('targeted train ','targeted validate ')):
                    job_limit_s=30*60
                if job['status']!='completed':reserved+=job_limit_s
                census.append(dict(id=job['id'],run=run['id'],status=job['status'],elapsed_s=elapsed,job_limit_s=job_limit_s))
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
