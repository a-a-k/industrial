"""Describe delays of one fixed archived plan; no causal or correction claim."""
import csv
import os
from pathlib import Path
from .common import actions_only,digest,read_json,read_rows,write_json
from .production import check_physics,compare,outcomes,product_ledger
from .releases import fetch

ROOT=Path('output/plan-diagnostics')
BANK='calibration-bank-Mk10-F1-43690938905-1'
PARTS=('upstream_wait','machine_queue_wait','repair_wait','processing_pause')


def diagnose():
    ROOT.mkdir(parents=True,exist_ok=True);source,receipt=fetch(BANK,'output/diagnostic-source')
    bank=read_json(source/'bank.json');data=read_json(source/'dataset.json');scenarios=read_json(source/'scenarios.json.gz')
    if bank['status']!='COMPLETE' or bank['split']!='calibration' or bank['registered']!=512:
        raise ValueError('unavailable archived calibration bank')
    trajectories={}
    for engine in ('des','dag'):
        trajectories[engine]={}
        for path in sorted((source/engine).glob('*.jsonl')):
            for row in read_rows(path):
                if row['scenario_id'] in trajectories[engine]:raise ValueError('duplicate trajectory')
                trajectories[engine][row['scenario_id']]=row
    if any(len(v)!=512 for v in trajectories.values()):raise ValueError('incomplete archive')
    deadline=11*data['nominal_makespan']//10;ops=data['operations'];previous={}
    for queue in data['queues']:
        for a,b in zip(queue,queue[1:]):previous[b]=a
    labels=outcomes(product_ledger(data,scenarios,trajectories['des']),[j['id'] for j in data['jobs']],deadline)
    n=len(labels);failed=sum(v is False for v in labels.values())
    if any(v is None for v in labels.values()):raise ValueError('unknown external outcome')
    def empty():return dict(all_parts={p:0 for p in PARTS},failed_parts={p:0 for p in PARTS},
        failed_batches_direct=0,all_batches_direct=0,unstarted_at_deadline=0,unfinished_at_deadline=0)
    machines=[empty() for _ in data['queues']];operations=[empty() for _ in ops];example=None;checked=0
    for scenario in scenarios:
        aid=scenario['id'];row=trajectories['des'][aid];compare(row,trajectories['dag'][aid]);check_physics(data,scenario,row)
        if row['horizon']<deadline:raise ValueError('diagnostic horizon unavailable')
        down=[[] for _ in data['queues']]
        for m,a,b in scenario['failures']:down[m].append((a,b))
        work={o['id']:o['work'] for o in ops};work.update(dict(scenario['work_overrides']))
        parts=[];machine_direct=set()
        def finish(i):return min(deadline,row['finish'][i]) if row['finish'][i] is not None else deadline
        for o in ops:
            i=o['id'];planned=min(deadline,o['planned_start'])
            ready=min(deadline,max([o['release'],o['planned_start'],*[finish(p) for p in o['predecessors']]]))
            machine_ready=finish(previous[i]) if i in previous else 0;eligible=max(ready,machine_ready)
            started=row['start'][i] is not None and row['start'][i]<=deadline
            start=row['start'][i] if started else deadline;end=finish(i) if started else deadline
            downtime=sum(max(0,min(end,b)-max(start,a)) for a,b in down[o['machine']]) if started else 0
            served=end-start-downtime if started else 0
            current=dict(upstream_wait=ready-planned,machine_queue_wait=eligible-ready,
                repair_wait=start-eligible,processing_pause=downtime)
            if min(current.values())<0 or not 0<=served<=work[i]:raise ValueError('invalid observed delay accounting')
            if sum(current.values())!=end-planned-served:raise ValueError('non-disjoint delay accounting')
            # Eligibility waiting must be entirely in downtime for this fixed-queue policy.
            if current['repair_wait']!=sum(max(0,min(start,b)-max(eligible,a)) for a,b in down[o['machine']]):
                raise ValueError('unexplained post-eligibility waiting')
            complete=row['finish'][i] is not None and row['finish'][i]<=deadline
            if complete and served!=work[i]:raise ValueError('finished work mismatch')
            direct=current['repair_wait']+current['processing_pause']>0
            if direct:machine_direct.add(o['machine'])
            for target in (operations[i],machines[o['machine']]):
                for p in PARTS:
                    target['all_parts'][p]+=current[p]
                    if not labels[aid]:target['failed_parts'][p]+=current[p]
                target['unstarted_at_deadline']+=not started;target['unfinished_at_deadline']+=not complete
            operations[i]['all_batches_direct']+=direct
            operations[i]['failed_batches_direct']+=direct and not labels[aid]
            parts.append(dict(operation=i,job=o['job'],machine=o['machine'],started=started,complete=complete,
                              observed_service=served,**current));checked+=1
        for m in machine_direct:
            machines[m]['all_batches_direct']+=1;machines[m]['failed_batches_direct']+=not labels[aid]
        if example is None and not labels[aid]:
            job=next(j for j in data['jobs'] if row['finish'][j['final_operation']] is None or row['finish'][j['final_operation']]>deadline)
            pending=[job['final_operation']];visited=set();links=[]
            while pending:
                i=pending.pop()
                if i in visited:continue
                visited.add(i);o=ops[i];cur=parts[i]
                if cur['upstream_wait']:
                    latest=max(finish(p) for p in o['predecessors']) if o['predecessors'] else -1
                    for p in o['predecessors']:
                        if finish(p)==latest:links.append(dict(source=p,target=i,kind='observed_predecessor_wait'));pending.append(p)
                if cur['machine_queue_wait'] and i in previous:
                    p=previous[i];links.append(dict(source=p,target=i,kind='observed_machine_queue_wait'));pending.append(p)
            example=dict(attempt=aid,unfinished_job=job['id'],terminal_operation=job['final_operation'],
                observed_delay_ancestry=[parts[i] for i in sorted(visited)],links=links,
                interpretation='allocated observed waiting ancestry; not a counterfactual causal effect')
    def output_stats(stat):
        result={k:v for k,v in stat.items() if k not in ('all_parts','failed_parts')}
        result.update({p+'_mean_all':stat['all_parts'][p]/(100*n) for p in PARTS})
        result.update({p+'_mean_failed':stat['failed_parts'][p]/(100*failed) if failed else None for p in PARTS})
        return result
    machine_rows=[dict(machine=m,**output_stats(stat)) for m,stat in enumerate(machines)]
    operation_rows=[dict(operation=o['id'],job=o['job'],machine=o['machine'],
        compatible_machines=';'.join(str(a['machine']) for a in o['alternatives']),**output_stats(operations[o['id']])) for o in ops]
    key=lambda r:(-r['failed_batches_direct'],-(r['repair_wait_mean_failed']+r['processing_pause_mean_failed']))
    machine_rows.sort(key=key);operation_rows.sort(key=key)
    for name,rows in (('machines.csv',machine_rows),('operations.csv',operation_rows)):
        with (ROOT/name).open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    write_json(ROOT/'example.json',example)
    result=dict(status='COMPLETE',scope='descriptive fixed-plan archive diagnostics; no new executions or corrections',
        plan='frozen research Mk10/list_v1, not a real technologist-approved plant plan',bank=BANK,receipt=receipt,
        deadline=deadline,archive_horizon=next(iter(trajectories['des'].values()))['horizon'],batches=n,failed_batches=failed,
        operations_checked=checked,machines=machine_rows,operations=operation_rows,
        accounting='technology first, additional machine queue second, post-eligibility repair waiting third, active pauses fourth; nonoverlapping within each operation',
        censoring='unfinished/start times after deadline remain censored; deadline is not a completion time',
        causal_effect_established=False,correction_benefit_established=False,
        source_sha256=digest(Path('industrial/plan_diagnostics.py').read_bytes()),commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(ROOT/'DIAGNOSTICS.json',result)
    lines=['# Диагностика фиксированного плана Mk10','',
        'Исходное расписание сохранено. Это замороженный исследовательский пример Mk10/list_v1, а не реальный план, утверждённый технологом предприятия.',
        f'Использованы {n} сохранённых калибровочных виртуальных прогонов F1. Срывов срока {deadline/100:g}: {failed}. Новых прогонов, выбора другого расписания и исправлений в этом этапе нет.',
        '', 'Ожидания разложены без пересечений внутри операции: технологические предшественники сверх её планового старта; дополнительная очередь станка; ремонт после готовности к запуску; паузы уже начатой обработки. Времена после срока не приписываются завершению. Суммирование ожиданий разных операций не равно потерянному времени всей партии: задержка может передаваться по цепочке.',
        '', '## Кандидаты на слабые места', '',
        '| Станок | Неуспешных партий с прямой задержкой ремонта | Средняя прямая задержка на неуспешную партию | Среднее ожидание операций в очереди |',
        '|---|---:|---:|---:|']
    for r in machine_rows:
        lines.append(f'| {r["machine"]} | {r["failed_batches_direct"]}/{failed} | '
            f'{r["repair_wait_mean_failed"]+r["processing_pause_mean_failed"]:.2f} | {r["machine_queue_wait_mean_failed"]:.2f} |')
    lines+=['', 'Это наблюдаемые задержки, а не доказательство, что исправление первого станка даст наибольший эффект. Календарь отказов и положение операций в цепочке могут совместно влиять на картину. Для причинного вывода нужен отдельный проверочный прогон с явно заданным вмешательством.',
        '', '## Операции для проверки локальных корректировок', '',
        '| Операция | Заказ | Станок | Неуспешных партий с прямой задержкой | Совместимые станки по исходной технологии |', '|---|---|---|---:|---|']
    for r in operation_rows[:12]:
        lines.append(f'| {r["operation"]} | {r["job"]} | {r["machine"]} | {r["failed_batches_direct"]} | {r["compatible_machines"]} |')
    lines+=['', 'Индексы начинаются с нуля; время — в исходных единицах задачи, 100 ticks = 1 единица. Альтернативная совместимость ещё не означает допустимость переноса в конкретное место очереди.',
        'Следующий этап должен проверить локальное изменение очереди или назначения, сохранив остальные решения и технологические зависимости. Для него нужны проверка допустимости и новый независимый результат. Идеальная отмена поломки — только анализ чувствительности, а не обещанное физическое усиление.',
        'В example.json сохранена наблюдаемая цепочка ожиданий для первого неуспешного прогона и первого незавершённого заказа. Выбор примера детерминирован, его показатели не являются отдельной независимой выборкой.']
    (ROOT/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':actions_only();diagnose()
