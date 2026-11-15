"""Whole-input-to-risk comparison; all execution is restricted to Actions."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from .common import actions_only,canonical,digest,read_json,read_rows,rng,write_json

ROOT=Path('output/end-to-end')
METHODS=('s1_simpat','dag_direct','dag_simpat')
SOURCES=('industrial/end_to_end.py','industrial/targets.py','industrial/statistics.py',
         'industrial/inputs.py','industrial/production.py','planning/generator.py','engines/model.hpp',
         'engines/risk_main.cpp','engines/tsfg_op/operation_adapter.go')


def spec():return read_json('provenance/end_to_end.json')
def fingerprint():return {p:digest(Path(p).read_bytes()) for p in SOURCES}
def suffix():return os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']


def vmhwm():
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmHWM:'):return int(line.split()[1])*1024
    raise ValueError('VmHWM unavailable')


def run(command,timeout=1200,env=None):
    started=time.perf_counter()
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                             start_new_session=True,env=env)
    status='OK'
    try:out,err=process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        status='TIMEOUT'
        os.killpg(process.pid,signal.SIGTERM)
        try:out,err=process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);out,err=process.communicate()
    if status=='OK' and process.returncode:status='FAILED'
    return dict(status=status,returncode=process.returncode,wall_s=time.perf_counter()-started,
                stdout=out[-3000:],stderr=err[-3000:],timeout_s=timeout)


def timed(command,env=None):
    started=time.perf_counter();subprocess.run(command,check=True,env=env)
    return time.perf_counter()-started


def bootstrap_stop():
    started=float(Path('output/bootstrap-start.txt').read_text())
    write_json('output/bootstrap.json',dict(common_environment_s=time.time()-started,
                                           go_started_at=time.time()))


def build():
    from .releases import fetch
    ROOT.mkdir(parents=True,exist_ok=True)
    bootstrap=read_json('output/bootstrap.json')
    go_window=time.time()-bootstrap['go_started_at']
    started=time.perf_counter()
    source,receipt=fetch(spec()['preflight'],'output/e2e-preflight')
    if read_json(source/'preflight.json')['status']!='PASS':raise ValueError('bad frozen input')
    for instance in spec()['instances']:
        original=read_json(source/instance/'dataset.json')
        planned=read_json(f'results/cpsat/schedules/{instance}.json')
        if (planned['nominal_makespan']!=original['nominal_makespan'] or
            original['dataset_id']!=instance or planned['dataset_id']!=instance):
            raise ValueError('changed reference C0')
        for name,data in (('original',original),('cpsat',planned)):
            write_json(ROOT/'inputs'/instance/(name+'.json'),data)
    acquisition=time.perf_counter()-started
    flags=['-std=c++20','-O3','-DNDEBUG','-Wall','-Wextra','-Werror','-Ivendor']
    Path('build').mkdir(exist_ok=True)
    baseline=timed(['g++',*flags,'engines/risk_main.cpp','-o','build/risk-dag'])
    oracle=timed([sys.executable,'scripts/build.py'],env={**os.environ,'PUBLIC_ONLY':'1'})
    fetch_s1=timed([sys.executable,'scripts/fetch_tsfg.py'])
    s1=timed([sys.executable,'scripts/build.py'],env={**os.environ,'S1_ONLY':'1',
        'TSFG_TEST_EVIDENCE':str(source/'provenance/tsfg-provenance.json')})
    common=bootstrap['common_environment_s']+acquisition
    write_json(ROOT/'build.json',dict(status='PASS',common_environment_s=bootstrap['common_environment_s'],
        frozen_input_acquisition_s=acquisition,input_archive_sha256=receipt['archive_sha256'],
        go_setup_window_s=go_window,baseline_compile_s=baseline,s1_source_fetch_s=fetch_s1,
        s1_compile_s=s1,independent_oracle_compile_s=oracle,
        first_use_preparation_s=dict(s1_simpat=common+go_window+fetch_s1+s1,
                                    dag_direct=common+baseline,dag_simpat=common+baseline),
        first_use_scope='one complete environment/input acquisition and participant build; common once for each method',
        installed_request_scope='input problem file available; all parsing, validation, histories, native preparation/execution, analysis and output inside process',
        cpuinfo=Path('/proc/cpuinfo').read_text(),source=fingerprint(),commit=os.environ['GITHUB_SHA']))


def validate_data(data):
    from planning.generator import validate_problem
    validate_problem(data)
    if (any(o.get('optional',False) for o in data['operations']) or
        any(j.get('optional',False) for j in data['jobs']) or
        any(v is not True for v in data.get('quality_results',{}).values()) or
        data.get('extended_profile') or data.get('semantics')):
        raise ValueError('scalar measurement profile requires mandatory, accepted Mk operations')
    if data['delta']!=5 or any(o[key]%5 for o in data['operations']
                              for key in ('work','planned_start','release')):
        raise ValueError('scalar comparison requires the exact common five-tick grid')


def draw(data,law,split,n,deadline):
    from .inputs import calendar
    if law not in ('F1','F2') or n<=0 or deadline<0:raise ValueError('invalid risk condition')
    result=[];c0=data['nominal_makespan']
    for index in range(n):
        identity=f'{data["dataset_id"]}-{law}-{split}-{index:04d}'
        shared=law=='F2' and rng(identity,'mixture').random()<.5
        if shared:
            history,_=calendar(rng(identity,'shared'),c0,deadline)
            histories=[history for _ in data['queues']]
        else:
            histories=[calendar(rng(identity,'machine',m),c0,deadline)[0] for m in range(len(data['queues']))]
        result.append(dict(id=identity,failures=[[m,a,b] for m,hist in enumerate(histories) for a,b in hist],
                           work_overrides=[],shared_calendar=shared))
    return result


def native(data_path,scenarios_path,target,deadline,method,trace=False):
    env={**os.environ,'GOMAXPROCS':'1'}
    if trace:env['RISK_TRACE']='1'
    else:env.pop('RISK_TRACE',None)
    if method=='s1_simpat':
        env.update(TSFG_OP_DRIVER='true',TSFG_OUTPUT_PROFILE='RISK-ONLY')
        command=[str(Path('.private/runtime/tsfg').resolve()),'tsfg',str(data_path),
                 str(scenarios_path),str(target),'MISSION',str(deadline),'5']
    else:
        env.pop('TSFG_OUTPUT_PROFILE',None)
        command=[str(Path('build/risk-dag').resolve()),str(data_path),str(scenarios_path),
                 str(target),str(deadline)]
    # The outer fresh worker is a process-group leader; timeout kills its native
    # child too. Qualification uses the group-aware runner directly.
    subprocess.run(command,env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    return read_json(target)


def worker(problem_path,method,folder):
    import resource
    if method not in METHODS:raise ValueError('unknown method')
    started=time.perf_counter()
    root=Path(folder);root.mkdir(parents=True,exist_ok=True);phases={}
    t=time.perf_counter();problem=read_json(problem_path);data=problem['dataset']
    validate_data(data);deadline=problem['deadline']
    phases['read_validate_s']=time.perf_counter()-t
    t=time.perf_counter()
    histories=draw(data,problem['law'],problem['split'],problem['samples'],deadline)
    scenario_sha=digest(canonical(histories));write_json(root/'dataset.json',data)
    write_json(root/'scenarios.json',histories)
    phases['generate_serialize_histories_s']=time.perf_counter()-t
    t=time.perf_counter()
    primitive=native(root/'dataset.json',root/'scenarios.json',root/'native.json',deadline,method)
    phases['native_import_prepare_execute_export_s']=time.perf_counter()-t
    n=primitive['sample_count'];finished=primitive['finished_count']
    if n!=problem['samples'] or not 0<=finished<=n:raise ValueError('invalid native census')
    t=time.perf_counter()
    if method.endswith('simpat'):
        from .targets import query_reduced
        categories=[]
        if finished:categories.append(dict(values=[True,True],count=finished))
        if finished<n:categories.append(dict(values=[False,None],count=n-finished))
        model=dict(signal_ids=['timely','__logical_completions__'],sample_count=n,
                   observation_categories=categories)
        reduced=query_reduced(model)
        if reduced['guaranteed']!=reduced['possible']:raise ValueError('unexpected interval')
        successes=reduced['guaranteed']
    else:successes=finished
    from fractions import Fraction
    from .statistics import outer
    answer=dict(samples=n,successes=successes,probability=successes/n,
                probability_exact=str(Fraction(successes,n)),ci95=outer(successes,successes,n))
    write_json(root/'answer.json',answer)
    phases['reduce_count_confidence_output_s']=time.perf_counter()-t
    children=resource.getrusage(resource.RUSAGE_CHILDREN)
    own=resource.getrusage(resource.RUSAGE_SELF)
    if method=='s1_simpat':native_memory=read_json(root/'native.json.meta.json')['VmHWM_bytes']
    else:native_memory=primitive['VmHWM_bytes']
    write_json(root/'worker.json',dict(status='PASS',method=method,answer=answer,phases=phases,
        internal_wall_s=time.perf_counter()-started,cpu_s=own.ru_utime+own.ru_stime+children.ru_utime+children.ru_stime,
        worker_VmHWM_bytes=vmhwm(),native_VmHWM_bytes=native_memory,
        sum_individual_peaks_upper_bound_bytes=vmhwm()+native_memory,
        memory_scope='post-exec individual peaks; their sum is an upper bound, not a measured concurrent peak',
        scenario_sha256=scenario_sha,problem_sha256=digest(Path(problem_path).read_bytes())))
    (root/'dataset.json').unlink();(root/'scenarios.json').unlink()


def verify_case(data,histories,deadline,root):
    from .production import check_physics,compare,simulate
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    write_json(root/'dataset.json',data);write_json(root/'scenarios.json',histories)
    traces={}
    for method in ('dag_direct','s1_simpat'):
        target=root/(method+'.json')
        command=[sys.executable,'-m','industrial.end_to_end','trace-native',
                 str(root/'dataset.json'),str(root/'scenarios.json'),str(target),str(deadline),method]
        process=run(command,spec()['process_limit_s'])
        write_json(root/(method+'-process.json'),process)
        if process['status']!='OK':raise ValueError('scalar verification unavailable: '+method)
        traces[method]=read_json(target)['finished_at']
    des,dp=simulate(data,histories,root/'des','des',deadline)
    dag,gp=simulate(data,histories,root/'dag','dag',deadline)
    if len(des)!=len(histories) or len(dag)!=len(histories):raise ValueError('oracle unavailable')
    expected=[]
    for item in histories:
        left,right=des[item['id']],dag[item['id']]
        check_physics(data,item,left);check_physics(data,item,right);compare(left,right)
        expected.append(left['cmax'])
    if any(values!=expected for values in traces.values()):
        write_json(root/'mismatch.json',dict(expected=expected,traces=traces))
        raise ValueError('scalar deadline completion mismatch')
    result=dict(status='PASS',samples=len(histories),finished_count=sum(t is not None for t in expected),
                scenario_sha256=digest(canonical(histories)),processes=dp+gp)
    write_json(root/'verification.json',result);return result


def qualify():
    from tests.test_planning import problem
    root=ROOT/'qualification';root.mkdir(parents=True,exist_ok=True);checks=[]
    data=problem();validate_data(data)
    histories=[dict(id=name,failures=failures,work_overrides=overrides) for name,failures,overrides in (
        ('healthy',[],[]),('initial',[[0,0,15]],[]),('boundary',[[0,30,40]],[]),
        ('blocked',[[1,0,100]],[]),('repair',[[0,5,25],[0,25,30]],[]),
        ('work',[],[[0,40]]))]
    for deadline in (0,10,25,30,60,65):
        checks.append(verify_case(data,histories,deadline,root/f'boundary-{deadline}'))
    for instance in spec()['instances']:
        for plan in spec()['plans']:
            data=read_json(ROOT/'inputs'/instance/(plan+'.json'));validate_data(data)
            for law in spec()['laws']:
                deadline=11*data['nominal_makespan']//10
                bank=draw(data,law,spec()['split']+'-qualification',16,deadline)
                checks.append(verify_case(data,bank,deadline,root/f'{instance}-{plan}-{law}'))
    write_json(root/'qualification.json',dict(status='PASS',checks=checks,source=fingerprint(),
        profile=spec(),commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))


def measure(instance,runner):
    from .releases import fetch
    qualified,_=fetch('end-to-end-qualification-'+suffix(),'output/e2e-qualified')
    proof=read_json(qualified/'qualification/qualification.json')
    if proof['status']!='PASS' or proof['source']!=fingerprint() or proof['profile']!=spec():
        raise ValueError('measurement source has not passed qualification')
    root=ROOT/'measurement';root.mkdir(parents=True,exist_ok=True);records=[]
    if instance not in spec()['instances'] or runner not in spec()['runner_repetitions']:raise ValueError('undeclared cell')
    for plan in spec()['plans']:
        data=read_json(ROOT/'inputs'/instance/(plan+'.json'));validate_data(data)
        for law in spec()['laws']:
            case=f'{instance}-{plan}-{law}';folder=root/case;folder.mkdir()
            deadline=11*data['nominal_makespan']//10
            problem=dict(dataset=data,deadline=deadline,law=law,split=spec()['split'],samples=spec()['samples'])
            write_json(folder/'problem.json',problem)
            histories=draw(data,law,spec()['split'],spec()['samples'],deadline)
            verification=verify_case(data,histories,deadline,folder/'verification')
            for repeat in range(spec()['warmups']+spec()['measured_repetitions']):
                order=list(METHODS);rng('e2e-order-v1',instance,plan,law,runner,repeat).shuffle(order)
                for method in order:
                    output=folder/f'round-{repeat:02d}'/method
                    process=run([sys.executable,'-m','industrial.end_to_end','worker',
                        str(folder/'problem.json'),method,str(output)],spec()['process_limit_s'])
                    record=dict(case=case,instance=instance,plan=plan,law=law,runner=runner,
                        repeat=repeat,warmup=repeat<spec()['warmups'],method=method,process=process)
                    if process['status']=='OK':
                        observed=read_json(output/'worker.json')
                        if (observed['scenario_sha256']!=verification['scenario_sha256'] or
                            observed['answer']['successes']!=verification['finished_count']):
                            record['status']='INVALID_ANSWER'
                        else:record.update(status='COMPLETE',worker=observed)
                    else:record['status']=process['status']
                    records.append(record)
                    write_json(root/'measurement.json',dict(status='RUNNING',records=records,
                        instance=instance,runner=runner,source=fingerprint(),profile=spec()))
                    if record['status']!='COMPLETE':raise ValueError('required process incomplete; remaining cells are UNRUN')
    write_json(root/'measurement.json',dict(status='COMPLETE',records=records,instance=instance,
        runner=runner,source=fingerprint(),profile=spec(),commit=os.environ['GITHUB_SHA']))


def report():
    import statistics
    from .releases import fetch
    root=ROOT/'report';root.mkdir(parents=True,exist_ok=True);runs=[];missing=[];rows=[];all_records=[]
    for instance in spec()['instances']:
        for runner in spec()['runner_repetitions']:
            tag=f'end-to-end-{instance}-{runner}-{suffix()}'
            try:
                folder,receipt=fetch(tag,f'output/e2e-report-{instance}-{runner}')
                measurement=read_json(folder/'measurement/measurement.json')
                build_record=read_json(folder/'build.json')
                if measurement['profile']!=spec() or measurement['source']!=fingerprint():
                    raise ValueError('unqualified measurement version')
                all_records.extend(measurement['records'])
                runs.append(dict(instance=instance,runner=runner,release=tag,
                    archive_sha256=receipt['archive_sha256'],status=measurement['status'],
                    first_use_preparation_s=build_record['first_use_preparation_s']))
                for plan in spec()['plans']:
                    for law in spec()['laws']:
                        for method in METHODS:
                            cells=[r for r in measurement['records'] if r['plan']==plan and r['law']==law and
                                   r['method']==method and not r['warmup']]
                            if len(cells)!=5 or any(r['status']!='COMPLETE' for r in cells):
                                missing.append(dict(instance=instance,runner=runner,plan=plan,law=law,method=method));continue
                            answers=[r['worker']['answer'] for r in cells]
                            if any(a!=answers[0] for a in answers):raise ValueError('nonreproducible answer')
                            times=[r['process']['wall_s'] for r in cells]
                            median=statistics.median(times)
                            rows.append(dict(instance=instance,runner=runner,plan=plan,law=law,method=method,
                                answer=answers[0],wall_s=times,median_s=median,
                                preparation_s=build_record['first_use_preparation_s'][method],
                                first_use_total_s=build_record['first_use_preparation_s'][method]+median,
                                median_cpu_s=statistics.median(r['worker']['cpu_s'] for r in cells),
                                median_worker_VmHWM_bytes=statistics.median(r['worker']['worker_VmHWM_bytes'] for r in cells),
                                median_native_VmHWM_bytes=statistics.median(r['worker']['native_VmHWM_bytes'] for r in cells)))
            except Exception as error:missing.append(dict(instance=instance,runner=runner,release=tag,error=str(error)))
    comparisons=[]
    for instance in spec()['instances']:
        for plan in spec()['plans']:
            for law in spec()['laws']:
                triplets=[];win=True
                for runner in spec()['runner_repetitions']:
                    selected={r['method']:r for r in rows if (r['instance'],r['plan'],r['law'],r['runner'])==(instance,plan,law,runner)}
                    if set(selected)!=set(METHODS):win=False;continue
                    base=selected['dag_direct'];candidate=selected['s1_simpat']
                    if any(r['answer']!=base['answer'] for r in selected.values()):
                        missing.append(dict(instance=instance,plan=plan,law=law,runner=runner,error='different answers'));win=False
                    favorable=(candidate['median_s']<base['median_s'] and
                        all(a<b for a,b in zip(candidate['wall_s'],base['wall_s'])) and
                        candidate['first_use_total_s']<base['first_use_total_s'])
                    win=win and favorable
                    triplets.append(dict(runner=runner,speedup=base['median_s']/candidate['median_s'],
                        first_use_speedup=base['first_use_total_s']/candidate['first_use_total_s'],
                        rows=selected))
                comparisons.append(dict(instance=instance,plan=plan,law=law,
                    measured_advantage=win and len(triplets)==3,runners=triplets))
    complete=not missing and len(rows)==108
    verdict='PARTIAL' if not complete else ('MEASURED_ADVANTAGE_IN_NAMED_CONDITIONS' if any(c['measured_advantage'] for c in comparisons) else 'NO_ESTABLISHED_ADVANTAGE')
    result=dict(status='COMPLETE' if complete else 'PARTIAL',verdict=verdict,profile=spec(),
        comparisons=comparisons,rows=rows,runs=runs,missing=missing,commit=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],planned_independent_failure_scenarios=6144,
        verified_unique_failure_scenarios=1024*len({(r['instance'],r['law']) for r in all_records}),
        statistical_sample_per_condition=1024,expected_timed_processes_including_warmups=648,
        observed_process_attempts=len(all_records),
        observed_complete_processes=sum(r['status']=='COMPLETE' for r in all_records),
        observed_timeouts=sum(r['status']=='TIMEOUT' for r in all_records),
        observed_failed_or_invalid=sum(r['status'] not in ('COMPLETE','TIMEOUT') for r in all_records),
        scheduled_processes_without_available_record=max(0,648-len(all_records)))
    write_json(root/'RESULT.json',result)
    lines=['# Полное сравнение виртуальных краш-тестов','',f'Статус: **{result["status"]}**. Вывод: **{verdict}**.','',
        'S1/SIMPAT и прямая альтернатива получают один риск и один биномиальный интервал.',
        'Это сравнение полной стоимости существующих реализаций, а не проверка нового вероятностного оценивателя.','',
        'Время запроса включает новый процесс Python, чтение и проверку входа, генерацию воздействий, подготовку и исполнение native, подсчёт/сокращение SIMPAT, CI и сохранение ответа.',
        'Начальная подготовка окружения, получение исходников и сборка указаны отдельно и добавлены к стоимости первого использования.',
        'Проверки независимым DES/DAG и построение отчёта входят в бюджет кампании отдельно от стоимости участника.','',
        '| Задача | План | Закон | Успех | S1/SIMPAT, с | DAG/MC, с | DAG/SIMPAT, с | Ускорение S1 |',
        '|---|---|---|---:|---:|---:|---:|---:|']
    for condition in comparisons:
        for cell in condition['runners']:
            values=cell['rows'];a=values['s1_simpat'];b=values['dag_direct'];c=values['dag_simpat']
            lines.append(f'| {condition["instance"]}, runner {cell["runner"]} | {condition["plan"]} | {condition["law"]} | {a["answer"]["successes"]}/1024 | {a["median_s"]:.6f} | {b["median_s"]:.6f} | {c["median_s"]:.6f} | {cell["speedup"]:.4f} |')
    lines+=['','Каждое значение — медиана пяти новых процессов на одном runner после отдельного прогрева.',
        'Сравнивать разные runner как одну пару нельзя. Повторы не увеличивают 1024 независимых испытания.',
        'Полные начальные затраты, CPU, post-exec VmHWM, все повторы, исходы и пропуски сохранены в RESULT.json и первичных выпусках.',
        'Масштаб законов и производственный срок одинаковы для обоих планов и основаны на исходном C0.',
        'Ни отрицательный результат этой серии, ни положительный результат отдельного условия не являются универсальной теоремой о любых реализациях TSFG.']
    if missing:lines+=['',f'Незавершённых обязательств: {len(missing)}. Их нельзя заменять результатами завершённых подмножеств.']
    (root/'REPORT_RU.md').write_text('\n'.join(lines)+'\n')
    if not complete:raise SystemExit('Required end-to-end evidence is incomplete')


def main():
    actions_only();command=sys.argv[1]
    if command=='bootstrap-stop':bootstrap_stop()
    elif command=='build':build()
    elif command=='qualify':qualify()
    elif command=='worker':worker(sys.argv[2],sys.argv[3],sys.argv[4])
    elif command=='trace-native':
        native(Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4]),int(sys.argv[5]),sys.argv[6],True)
    elif command=='measure':measure(sys.argv[2],int(sys.argv[3]))
    elif command=='report':report()
    else:raise ValueError('unknown command')


if __name__=='__main__':main()
