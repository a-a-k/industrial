"""Reproduce boundary defects and verify fixes without rerunning campaigns."""
import base64
import cProfile
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import pstats
import statistics
import subprocess
import sys
from . import binding
from .common import actions_only,canonical,digest,execute,read_json,write_json
from .measurement import prepare,run_method
from .model import identify
from .production import check_physics,compare,export_observations,outcomes,product_ledger,simulate
from .releases import fetch
from .targets import direct,project_full,query_full_r,query_reduced
from planning.generator import validate_problem
from tests.test_binding_edges import packet


REFERENCE='0d33330a49bcf05512cf0b669e64429cbb59ce4c'
REFERENCES={'industrial/binding.py':'0a9a652c38cbbc7e2ebddd88d80d16551c5049f0',
    'planning/generator.py':'f2ce0b23be67f6190839092f6170a2bea0947d65',
    'industrial/qualification.py':'189586cc0a61021701ecb21a1cc3f82b5ac67ad3'}


def reference(root,path):
    raw=subprocess.check_output(['gh','api',f'repos/{os.environ["GITHUB_REPOSITORY"]}/contents/{path}?ref={REFERENCE}'],text=True)
    payload=json.loads(raw)
    if payload['sha']!=REFERENCES[path]:raise ValueError('unexpected old source blob')
    saved=root/('reference-'+path.replace('/','-'));saved.write_bytes(base64.b64decode(payload['content']))
    package='industrial' if path.startswith('industrial/') else 'planning'
    module_spec=importlib.util.spec_from_file_location(package+'.audit_reference_'+Path(path).stem,saved)
    module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    return module


def capture(call):
    try:return dict(status='OK',value=call())
    except Exception as error:return dict(status=type(error).__name__,message=str(error))


def run():
    root=Path('output/implementation-audit');root.mkdir(parents=True,exist_ok=True)
    old=reference(root,'industrial/binding.py');old_planner=reference(root,'planning/generator.py')
    reference(root,'industrial/qualification.py');edges=[]
    data=packet();data['records'].append(dict(attempt='a',kind='reassign',op=0,machine=0,time=101))
    for label,module in (('old',old),('fixed',binding)):
        full=capture(lambda:list(module.bind(data['contract'],data['attempts'],data['records'],50)[1]))
        reduced=capture(lambda:list(module.direct_rows(data['contract'],data['attempts'],data['records'],50)))
        edges.append(dict(case='out_of_window_reassignment',version=label,full=full['status'],direct=reduced['status']))
    data=packet();data['attempts'][0]['finished_at']=-1
    for label,module in (('old',old),('fixed',binding)):
        edges.append(dict(case='negative_completion_timestamp',version=label,
            full=capture(lambda:module.bind(data['contract'],data['attempts'],data['records'],50))['status'],
            direct=capture(lambda:list(module.direct_rows(data['contract'],data['attempts'],data['records'],50)))['status']))
    branch=dict(dataset_id='audit-branch',delta=5,nominal_makespan=100,queues=[[0],[1]],
        jobs=[dict(id=0,release=0,final_operation=0)],operations=[
            dict(id=0,job=0,release=0,predecessors=[],machine=0,work=10,planned_start=0,planned_end=10,alternatives=[dict(machine=0,work=10)]),
            dict(id=1,job=0,release=0,predecessors=[],machine=1,work=100,planned_start=0,planned_end=100,alternatives=[dict(machine=1,work=100)])])
    acceptance=dict(old=capture(lambda:old_planner.validate_problem(branch))['status'],
        fixed=capture(lambda:validate_problem(branch))['status'])
    scenario=dict(id='branch-terminal-counterexample',failures=[],work_overrides=[]);trajectories=[]
    for engine in ('des',):
        rows,ps=simulate(branch,[scenario],root/'branch'/engine,engine,50)
        if any(p['status']!='OK' for p in ps):raise ValueError('counterexample participant failed')
        check_physics(branch,scenario,rows[scenario['id']]);trajectories.append(rows[scenario['id']])
    traces={scenario['id']:trajectories[0]};ledger=product_ledger(branch,[scenario],traces)
    observed=export_observations(branch,[scenario],traces,50);model,_,_=binding.fit(observed,50)
    counterexample=dict(input_validation=acceptance,ledger_success=outcomes(ledger,[0],50)[scenario['id']],
        full_R=query_full_r(model),mandatory_finished=all(v is not None and v<=50 for v in trajectories[0]['finish']))
    if counterexample['ledger_success'] is not True or counterexample['full_R']['upper']!=0 or counterexample['mandatory_finished']:
        raise ValueError('the old unsupported-terminal counterexample was not reproduced')
    preflight,_=fetch('preflight-43639035427-1','output/audit-preflight');valid=[]
    for i in range(1,11):
        instance=f'Mk{i:02d}';validate_problem(read_json(preflight/instance/'dataset.json'));valid.append(instance)
    observations,_=fetch('calibration-observations-Mk10-F2-43690938905-1','output/audit-observations')
    index=read_json(observations/'index.json');checks=[];profile_packet=None;profile_deadline=None
    for entry in index['cases']:
        data=read_json(observations/entry['file']);deadline=entry['deadline']
        proto,rows,_=binding.bind(data['contract'],data['attempts'],data['records'],deadline)
        full=identify(proto,rows);projected=project_full(full)
        previous=direct(old.direct_rows(data['contract'],data['attempts'],data['records'],deadline),proto['completion_signals'])
        current=direct(binding.direct_rows(data['contract'],data['attempts'],data['records'],deadline),proto['completion_signals'])
        good=projected==previous==current and query_full_r(full)==query_reduced(current)
        checks.append(dict(case=entry.get('case',entry['file']),deadline=deadline,status='PASS' if good else 'FAIL',R=query_reduced(current)))
        if entry['deadline_label']=='110' and entry['mode']=='mcar30':profile_packet=observations/entry['file'];profile_deadline=deadline
    phase_cases=[]
    for number,tag in enumerate(('measurement-extended-Mk10-F2-mcar30-100000-R-full-projection-43726894373-1',
            'measurement-Mk10-F2-mcar30-100000-R-full-direct-43709223426-1')):
        measured,receipt=fetch(tag,f'output/audit-measurement-{number}');record=read_json(measured/'measurement.json');summary=[]
        for method in record['summary']:
            runs=[a for a in record['attempts'] if a['method']==method and not a['warmup']]
            if len(runs)!=5 or any(a['status']!='OK' for a in runs):raise ValueError('incomplete quoted timing')
            wall=statistics.median(a['process']['wall_s'] for a in runs)
            if wall!=record['summary'][method]['median_wall_s']:raise ValueError('published median differs from raw attempts')
            for attempt in record['attempts']:
                if attempt['method']!=method:continue
                saved=measured/f"{attempt['repeat']}-{method}.json.model.json.gz"
                model=read_json(saved);answer=query_full_r(model) if method=='full' else query_reduced(model)
                if answer!=attempt['measurement']['estimates']['R']:raise ValueError('saved representation gives another R')
                if saved.stat().st_size!=attempt['measurement']['representation_bytes']:raise ValueError('quoted file size differs')
            phases={k:statistics.median(a['measurement']['phases'][k] for a in runs)
                for k in ('parse_bind_build_s','serialize_s','analysis_s')}
            summary.append(dict(method=method,wall_s=wall,bytes=record['summary'][method]['median_representation_bytes'],phases=phases))
        phase_cases.append(dict(release=tag,archive_sha256=receipt['archive_sha256'],case=record['case'],methods=summary,
            R=record['attempts'][0]['measurement']['estimates']['R'],log_sha256=read_json(measured/'load/log-receipt.json')['sha256']))
    if phase_cases[0]['log_sha256']!=phase_cases[1]['log_sha256']:raise ValueError('compared computational inputs differ')
    load=root/'profile-load';prepare(profile_packet,load,1000);profiling=[]
    for method in ('full','projection','direct'):
        destination=root/('profile-'+method)
        process=execute([sys.executable,'-m','industrial.implementation_audit','profile',str(load),method,str(profile_deadline),str(destination)])
        if process['status']!='OK':raise ValueError('profile child failed: '+str(process))
        profiling.append(dict(method=method,process=process,result=read_json(destination/'measurement.json')))
    same=all(p['result']['estimates']==profiling[0]['result']['estimates'] for p in profiling)
    result=dict(status='PROBES_PASS' if all(r['status']=='PASS' for r in checks) and same
        and acceptance==dict(old='OK',fixed='ValueError') else 'FAIL',
        reference_commit=REFERENCE,source_blob_ids=REFERENCES,edge_cases=edges,
        rejected_terminal_counterexample=counterexample,frozen_instances_accept_new_guard=valid,
        clean_packet_checks=checks,profile_signatures_equal=same,phase_cases=phase_cases,
        core_test_environment_fixed=True,historical_production_results_recomputed=False,
        interpretation='quoted projection builds the full model first; direct reduced construction is a separate and faster recorded path',
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(root/'RESULT.json',result)
    lines=['# Аудит реализации и исправления','',f"Статус проверок: **{result['status']}**.",'',
        'В пути projection сначала выполняются чтение, привязка и построение полной модели; затем берётся её проекция. '
        'Поэтому близкие полные времена не доказывают отсутствия ускорения у прямого сокращённого построения.',
        '', '| Выпуск | Метод | Полное время, с | Чтение/привязка/построение, с | Сохранение, с | Запрос, с | gzip, байт |',
        '|---|---|---:|---:|---:|---:|---:|']
    for group in phase_cases:
        for row in group['methods']:
            p=row['phases'];lines.append(f"| {group['release']} | {row['method']} | {row['wall_s']:.6f} | {p['parse_bind_build_s']:.6f} | {p['serialize_s']:.6f} | {p['analysis_s']:.6f} | {row['bytes']} |")
    lines+=['', 'В таблице независимые медианы пяти процессов; их сумма не обязана равняться медиане полного времени. '
        'Сравнивать времена методов следует внутри одной пары на одном runner. '
        'Обе пары имеют одинаковый SHA входного журнала, но разные runners. '
        'Точное R здесь является интервалом [0, 52147/100000]. Файл 146 байт сохраняет R, но не все структурные запросы полной модели.',
        '', 'Исправлены расхождения direct/full при обработке записей вне временного окна и неверных времён завершения; '
        'усилена проверка терминальной операции задания до генерации; core-тесты отделены от CP-тестов в другой среде.',
        f"Все десять замороженных Mk-входов прошли новую проверку; {len(checks)} масок/сроков Mk10-F2 дали те же точные reduced-модели до и после исправления. "
        'Исходные Mk-задания являются цепочками, а проблемный разветвлённый контракт теперь отвергается до исполнения.',
        'Диагностические профили 1000 повторённых попыток не заменяют обязательные измерения: cProfile добавляет накладные расходы. '
        'Архивные производственные результаты и времена сохранены без перезаписи.']
    (root/'AUDIT_RU.md').write_text('\n'.join(lines)+'\n')
    if result['status']!='PROBES_PASS':raise SystemExit('implementation audit failed')


def finalize():
    import re
    root=Path('output/implementation-audit');result=read_json(root/'RESULT.json')
    core=read_json('output/qualification/qualification.json')
    if result['status']!='PROBES_PASS' or core['status']!='CORE_PASS':raise ValueError('audit or core qualification incomplete')
    counts={}
    for name in ('planning','cp'):
        content=(root/(name+'-tests.txt')).read_text()
        if '\nOK\n' not in content or '\nFAILED' in content:raise ValueError('separate suite failed')
        counts[name]=int(re.search(r'Ran (\d+) tests?',content).group(1))
    result.update(status='PASS',core_tests=core['tests'],separate_tests=counts,
        all_tests=core['tests']+sum(counts.values()))
    write_json(root/'RESULT.json',result)
    with (root/'AUDIT_RU.md').open('a') as stream:
        stream.write(f"\nИтоговая квалификация: core {core['tests']}, planning {counts['planning']}, CP {counts['cp']}; всего {result['all_tests']}, ошибок нет.\n")


def profile_child(load,method,deadline,destination):
    root=Path(destination);root.mkdir(parents=True,exist_ok=True)
    profiler=cProfile.Profile();profiler.runcall(run_method,load,method,'R',deadline,root/'measurement.json')
    with (root/'profile.txt').open('w') as stream:pstats.Stats(profiler,stream=stream).sort_stats('cumulative').print_stats(25)


if __name__=='__main__':
    actions_only()
    if len(sys.argv)>1 and sys.argv[1]=='profile':profile_child(sys.argv[2],sys.argv[3],int(sys.argv[4]),sys.argv[5])
    elif len(sys.argv)>1 and sys.argv[1]=='finalize':finalize()
    else:run()
