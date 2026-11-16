"""Present every sealed inverse condition with simultaneous certification bounds."""
import csv
from pathlib import Path
import shutil
from .common import canonical,digest,read_json,write_json
from .inverse_conditions import ROOT,fingerprint,spec,stamp
from .inverse_math import identity
from .releases import fetch
from .statistics import lower,upper


def csv_file(path,rows):
    if not rows:return
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def cost(c):return (c['distance']['assignments'],c['distance']['queue_inversions'],1-c['rho'])
def dominates(a,b):return all(x<=y for x,y in zip(cost(a),cost(b))) and any(x<y for x,y in zip(cost(a),cost(b)))


def row(c):
    return dict(instance=c['instance'],law=c['law'],plan=c['plan'],rho=c['rho'],
        mean_repair_before_rounding=c['raw_mean_repair_ticks']/100,nominal=c['nominal']/100,deadline=c['deadline']/100,
        reassigned_operations=c['distance']['assignments'],queue_inversions=c['distance']['queue_inversions'],
        successes=c['successes'],samples=c['samples'],probability=c['probability'],lower=c['lower'],upper=c['upper'],
        classification=c['status'],empirical_analytic_lower=c['empirical_analytic_bounds'][0],
        empirical_analytic_upper=c['empirical_analytic_bounds'][1])


def report(registry):
    cfg=spec();ROOT.mkdir(parents=True,exist_ok=True);records=[];seen=set();missing=[]
    source,receipt=fetch(registry['seal'],'output/inverse-report-seal');seal=read_json(source/'seal.json')
    if seal['status']!='SEALED' or seal['implementation']!=fingerprint() or seal['spec']!=cfg:raise ValueError('inverse report seal mismatch')
    catalogues={r['instance']:r for r in seal['catalogues']}
    expected={(i,l) for i in cfg['instances'] for l in cfg['laws']}
    actual_family=sum(len(r['plans']) for r in catalogues.values())*len(cfg['laws'])*len(cfg['repair_multipliers'])
    if actual_family!=seal['configurations'] or seal['one_sided_alpha']!=cfg['confidence_family_error']/(2*actual_family):
        raise ValueError('pre-bank statistical family changed')
    for index,tag in enumerate(registry.get('certifications',[])):
        try:
            folder,rcpt=fetch(tag,f'output/inverse-certification-{index}');r=read_json(folder/'certification.json')
            key=(r['instance'],r['law'])
            if key not in expected or key in seen or r['status']!='PASS' or r['implementation']!=fingerprint() or r['spec']!=cfg:
                raise ValueError('incomplete or duplicate inverse certification')
            if r['seal_release']!=registry['seal'] or r['seal_receipt']['archive_sha256']!=receipt['archive_sha256']:
                raise ValueError('mixed inverse global seals')
            cat=catalogues[r['instance']]
            if canonical(r['catalogue'])!=canonical(cat):raise ValueError('sealed plan menu changed')
            required={(p['key'],rho) for p in cat['plans'] for rho in cfg['repair_multipliers']}
            if {(c['plan'],c['rho']) for c in r['conditions']}!=required or len(r['conditions'])!=len(required):
                raise ValueError('not all registered conditions were certified')
            for c in r['conditions']:
                p=next(p for p in cat['plans'] if p['key']==c['plan']);a=seal['one_sided_alpha']
                if (c['samples']!=cfg['certification_samples'] or c['one_sided_alpha']!=a or c['analytic_mismatches']!=0
                    or c['distance']!=p['distance'] or c['schedule_sha256']!=p['schedule_sha256']):
                    raise ValueError('condition scope or physical data changed')
                if abs(c['lower']-lower(c['successes'],c['samples'],a))>1e-12 or abs(c['upper']-upper(c['successes'],c['samples'],a))>1e-12:
                    raise ValueError('simultaneous exact binomial bounds changed')
                status='FEASIBLE' if c['lower']>=cfg['target_probability'] else 'INFEASIBLE' if c['upper']<cfg['target_probability'] else 'UNRESOLVED'
                if c['status']!=status:raise ValueError('condition classification changed')
            seen.add(key);records.append(dict(certification_release=tag,certification_receipt=rcpt,**r))
        except Exception as error:missing.append(dict(release=tag,error=str(error)))
    missing.extend(dict(instance=i,law=l,error='required inverse certification missing') for i,l in sorted(expected-seen))
    summaries=[];all_rows=[];frontier_rows=[];cost_rows=[];catalogue_cost_rows=[];recommendations=[]
    for instance,cat in sorted(catalogues.items()):
        catalogue_cost_rows.append(dict(instance=instance,catalogue_release=cat['release'],
            catalogue_request_wall_s=cat['catalogue_wall_s'],candidate_family_wall_s=cat['candidate_family_wall_s'],
            input_and_qualification_retrieval_s=cat['input_and_qualification_retrieval_s'],
            scope='once per instance, shared by F1 and F2; excludes environment and compilation'))
        for p in cat['plans']:
            dest=ROOT/'plans'/instance/p['key'];dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(source/instance/'plans'/p['key'],dest)
    for r in sorted(records,key=lambda r:(r['instance'],r['law'])):
        i,l=r['instance'],r['law'];conditions=r['conditions'];feasible=[c for c in conditions if c['status']=='FEASIBLE']
        frontier=[c for c in feasible if not any(dominates(other,c) for other in feasible)]
        frontier.sort(key=lambda c:(cost(c),c['nominal'],c['plan']))
        case=ROOT/'cases'/(i+'-'+l);case.mkdir(parents=True)
        base=read_json(source/i/'base/schedule.json');base_key=identity(base)
        original=next(c for c in conditions if c['plan']==base_key and c['rho']==1)
        unchanged_feasible=[c for c in feasible if c['plan']==base_key]
        unchanged=max(unchanged_feasible,key=lambda c:c['rho']) if unchanged_feasible else None
        rows=[row(c) for c in sorted(conditions,key=lambda c:(cost(c),c['plan']))];all_rows.extend(rows);csv_file(case/'conditions.csv',rows)
        local_front=[]
        for c in frontier:
            competitors=[o for o in conditions if dominates(o,c)]
            unresolved=[o for o in competitors if o['status']=='UNRESOLVED']
            minimum=all(o['upper']<cfg['target_probability'] for o in competitors)
            item=dict(row(c),minimum_proved_in_menu=minimum,unresolved_dominating_options=len(unresolved),
                schedule=f'plans/{i}/{c["plan"]}/schedule.csv',diff=f'plans/{i}/{c["plan"]}/diff.json')
            local_front.append(item);frontier_rows.append(item)
        recommendations.extend(local_front)
        summary=dict(instance=i,law=l,registered_conditions=len(conditions),certified_feasible=len(feasible),
            certified_infeasible=sum(c['status']=='INFEASIBLE' for c in conditions),unresolved=sum(c['status']=='UNRESOLVED' for c in conditions),
            baseline_probability=original['probability'],baseline_lower=original['lower'],baseline_upper=original['upper'],baseline_status=original['status'],
            largest_certified_repair_multiplier_unchanged=unchanged['rho'] if unchanged else None,
            unchanged_certified_probability=unchanged['probability'] if unchanged else None,
            unchanged_certified_lower=unchanged['lower'] if unchanged else None,
            original_raw_mean_repair=original['raw_mean_repair_ticks']/100,
            unchanged_certified_raw_mean_repair=unchanged['raw_mean_repair_ticks']/100 if unchanged else None,
            frontier_options=len(frontier),frontier_minimum_proved=sum(v['minimum_proved_in_menu'] for v in local_front))
        summaries.append(summary)
        cost_rows.append(dict(instance=i,law=l,certification_request_wall_s=r['wall_s'],
            scope='certification request only; excludes environment and compilation; shared catalogue counted separately once',
            production_scalar_samples=sum(c['samples'] for c in conditions),
            risk_dag_samples=sum(c['samples'] for c in conditions),s1_scalar_samples=sum(c['s1_scalar_samples'] for c in conditions),
            full_trace_samples_per_engine=sum(c['full_trace_samples'] for c in conditions)))
        lines=[f'# {i}, {l}: план и требования к ремонту','',
            f'Станки и вся партия сохранены. Прежний срок {original["deadline"]/100:g}. '
            f'Зарегистрировано {len(conditions)} сочетаний, каждое проверено на {cfg["certification_samples"]} новых сценариях.',
            f'Исходные план и ремонт: вероятность по прогонам {100*original["probability"]:.2f}%, '
            f'общая нижняя граница {100*original["lower"]:.2f}%; статус {original["status"]}.',
            '', '## Подтверждённое меню', '',
            '| Переназначено операций | Инверсий очереди | Средний ремонт от исходного | Средний ремонт до округления | Вовремя | Общая нижняя граница | Минимальность внутри меню | План |',
            '|---:|---:|---:|---:|---:|---:|---|---|']
        for c in local_front:
            lines.append(f'| {c["reassigned_operations"]} | {c["queue_inversions"]} | {100*c["rho"]:g}% | '
                f'{c["mean_repair_before_rounding"]:.4f} | {100*c["probability"]:.2f}% | {100*c["lower"]:.2f}% | '
                f'{"подтверждена" if c["minimum_proved_in_menu"] else "не установлена"} | [CSV](../../{c["schedule"]}) |')
        if not local_front:lines+=['', 'Ни одно зарегистрированное сочетание пока не подтверждает требуемые95%.']
        original_analysis=read_json(source/i/'plans'/base_key/'analysis.json')
        lines+=['', '## Аналитические ограничения', '',
            f'В общей календарной ветви вся партия успевает тогда и только тогда, когда суммарный простой до срока '
            f'не превышает {original_analysis["shared_calendar_downtime_budget"]/100:g}. Это условие текущего раннего плана, '
            'а не верхняя граница длительности каждого отдельного ремонта.',
            '', 'Следующие необходимые условия выведены из временных окон операций. Если в данном окне станок не даст '
            'нужный объём обслуживания, эта партия к сроку не успеет. Прохождение всех показанных окон само по себе успех не гарантирует.',
            '', '| Станок | Начало окна | Конец окна | Нужное рабочее время | Нарушений в исходном режиме |',
            '|---|---:|---:|---:|---:|']
        for w in sorted(original['windows'],key=lambda w:(-w['violations'],w['machine'],w['begin'],w['end']))[:12]:
            lines.append(f'| {w["machine"]} | {w["begin"]/100:g} | {w["end"]/100:g} | {w["required"]/100:g} | {w["violations"]}/{original["samples"]} |')
        lines+=['', 'Одна партия может нарушить несколько окон; числа нарушений не складываются в число независимых испытаний.',
            'Достаточный сертификат использует время, когда все используемые станки одновременно исправны. '
            'Границы empirical_analytic_lower/upper в conditions.csv относятся к доле данного банка, а не являются границами истинной вероятности. '
            'Критерий95% проверяется по точным биномиальным границам фактического выпуска независимого DES.',
            '', 'Все сочетания, в том числе неопределённые и неудачные, находятся в conditions.csv. '
            'Границы одновременно покрывают всё зарегистрированное семейство; выбор показанного Парето-меню не превращает этот же банк в новый независимый тест.',
            'Минимальность подтверждается только если все менее требовательные зарегистрированные варианты доказанно не достигают95%. '
            'При неопределённых конкурентах минимальность не установлена. Все возможные расписания и индивидуальные ремонты станков не оптимизировались.',
            'Единицы времени исходные, не реальные минуты; в JSON/CSV расписаний100ticks=1единица. Средние ремонты указаны ДО округления вверх к шагу0,05. '
            'Достижимость этих средних на реальном предприятии и денежные затраты не проверялись.']
        (case/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    for name,values in [('conditions.csv',all_rows),('frontier.csv',frontier_rows),('summary.csv',summaries),
        ('costs.csv',cost_rows),('catalogue_costs.csv',catalogue_cost_rows)]:csv_file(ROOT/name,values)
    budget=read_json('output/budget.json')
    csv_file(ROOT/'campaign_job_costs_at_report_start.csv',budget['jobs'])
    complete=not missing and seen==expected and len(all_rows)==seal['configurations']
    all_feasible=complete and all(s['frontier_options']>0 for s in summaries)
    interpretation=dict(
        baseline_certified_feasible_cases=sum(s['baseline_status']=='FEASIBLE' for s in summaries),
        baseline_certified_infeasible_cases=sum(s['baseline_status']=='INFEASIBLE' for s in summaries),
        baseline_unresolved_cases=sum(s['baseline_status']=='UNRESOLVED' for s in summaries),
        menu_minimality_confirmed_cases=sum(s['frontier_minimum_proved']>0 for s in summaries),
        menu_minimality_unresolved_cases=sum(s['frontier_options']>0 and s['frontier_minimum_proved']==0 for s in summaries),
        frontier_options_with_plan_changes=sum(c['reassigned_operations']>0 or c['queue_inversions']>0 for c in frontier_rows),
        conditions_by_status={status:sum(c['classification']==status for c in all_rows) for status in ('FEASIBLE','INFEASIBLE','UNRESOLVED')})
    result=dict(technical_status='COMPLETE' if complete else 'PARTIAL',
        functional_status='ALL_CASES_HAVE_CERTIFIED_CONDITIONS' if all_feasible else 'TARGET_NOT_CERTIFIED_ALL_CASES',
        required_cases=20,completed_cases=len(seen),required_configurations=seal['configurations'],completed_configurations=len(all_rows),
        confidence_family=dict(error=.05,one_sided_alpha=seal['one_sided_alpha'],bounds=2*seal['configurations']),
        summaries=summaries,frontier=frontier_rows,certifications=records,missing=missing,seal_release=registry['seal'],seal_receipt=receipt,
        previous_comparative_claim='NOT_ESTABLISHED',global_optimality_claimed=False,real_plant_validation=False,interpretation=interpretation,
        execution_totals=dict(production_scalar_samples=sum(c['samples'] for r in records for c in r['conditions']),
            risk_dag_samples=sum(c['samples'] for r in records for c in r['conditions']),
            s1_scalar_samples=sum(c['s1_scalar_samples'] for r in records for c in r['conditions']),
            full_trace_samples_per_engine=sum(c['full_trace_samples'] for r in records for c in r['conditions'])),
        report_source_sha256=digest(Path('industrial/inverse_report.py').read_bytes()),implementation=fingerprint(),spec=cfg,**stamp())
    write_json(ROOT/'RESULT.json',result)
    lines=['# Условия выполнения партии с вероятностью не ниже95%','',
        f'Расчёт **{result["technical_status"]}**: {len(seen)}/20 условий, {len(all_rows)}/{seal["configurations"]} зарегистрированных сочетаний.',
        f'Условий с хотя бы одним подтверждённым вариантом: {sum(s["frontier_options"]>0 for s in summaries)}/20.',
        '', 'Результат — конкретные планы и требования к среднему ремонту при прежних станках, партии и сроке. '
        'У показанных подтверждённых вариантов общая нижняя граница вероятности выпуска не ниже95%. '
        'Это условие заданной синтетической модели; достижимость ремонта и цены на реальном предприятии неизвестны.',
        '', f'Исходные условия уже подтверждённо проходят цель в {interpretation["baseline_certified_feasible_cases"]} случаях; '
        f'подтверждённо не проходят в {interpretation["baseline_certified_infeasible_cases"]}; '
        f'остаются неопределёнными в {interpretation["baseline_unresolved_cases"]}. '
        f'Минимальность усиления внутри меню подтверждена в {interpretation["menu_minimality_confirmed_cases"]} случаях; '
        f'в {interpretation["menu_minimality_unresolved_cases"]} найдены достаточные условия без доказанного минимума.',
        ('Все варианты, недоминируемые среди подтверждённо допустимых, сохраняют исходный план. '
        'Проверенные изменения расписаний не позволили ослабить подтверждённые требования к ремонту на выбранной сетке. '
        'Получены требования к среднему ремонту для уже заданных планов. Вывод о перепланировании относится к зарегистрированному меню.'
        if complete and interpretation['frontier_options_with_plan_changes']==0 else
        'В подробностях показаны все недоминируемые среди подтверждённо допустимых сочетания изменений плана и ремонта.'),
        '', 'Для быстрого прочтения:100% ремонта в следующей таблице означает, что исходные план и ремонт уже проходят цель. '
        '50% означает подтверждённый вариант с тем же планом и вдвое меньшим средним экспоненциальной длительности ремонта ДО округления. '
        'Из-за округления вверх фактическое среднее не обязано уменьшиться ровно вдвое. '
        'Это самый мягкий подтверждённый уровень сетки при исходном плане; дополнительные варианты с правками расписания — в подробностях. '
        'Минимальность не следует из одного подтверждённого варианта и проверяется отдельно.',
        '', '| Задача | Закон | Исходная частота вовремя | Средний ремонт от исходного без правок плана | Подтверждённых вариантов | Вариантов Парето | Минимальных внутри меню | Подробности |',
        '|---|---|---:|---:|---:|---:|---:|---|']
    for s in summaries:
        repair='не подтверждено' if s['largest_certified_repair_multiplier_unchanged'] is None else f'{100*s["largest_certified_repair_multiplier_unchanged"]:g}%'
        lines.append(f'| {s["instance"]} | {s["law"]} | {100*s["baseline_probability"]:.2f}% | {repair} | {s["certified_feasible"]} | '
            f'{s["frontier_options"]} | {s["frontier_minimum_proved"]} | [Условия и расписания](cases/{s["instance"]}-{s["law"]}/REPORT_RU.md) |')
    lines+=['', 'Подбор использует сильный стандартный CP/DAG как основной инструмент. Предыдущее сравнительное преимущество '
        'S1/SIMPAT остаётся NOT_ESTABLISHED; этот расчёт не переписывает отрицательные результаты прошлой серии.',
        'Все планы и уровни ремонта были зафиксированы до нового банка. Для каждого сочетания независимый DES и прямой DAG '
        'проверили8192 исхода; исходный S1 — первые128 скалярных исходов и16 полных трасс. Все выполненные проверки должны совпадать.',
        'Семейство включает все зарегистрированные сочетания. Две односторонние границы Клоппера—Пирсона с alpha=0,05/(2N) '
        'обеспечивают совместное покрытие не ниже95%. Неопределённые условия сохранены, а не объявлены неуспешными.',
        'Парето сравнивает число переназначений, инверсии очередей и уменьшение среднего ремонта без придуманных денежных весов. '
        'Минимальность относится только к зарегистрированному меню и подтверждается лишь при исключении всех менее требовательных вариантов. '
        'Глобальная оптимальность среди всех расписаний и всех индивидуальных ремонтных политик не заявляется.',
        'conditions.csv содержит все результаты; frontier.csv — варианты, недоминируемые среди подтверждённо допустимых. '
        'Неопределённый вариант ещё может их доминировать; доказанная минимальность отдельно отмечена полем minimum_proved_in_menu. '
        'catalogue_costs.csv учитывает построение каждого семейства ОДИН раз для обеих моделей поломок; costs.csv —20 отдельных запросов сертификации. '
        'Эти времена запросов включают передачу входов, но исключают подготовку окружения и компиляцию. '
        'Полный снимок затрат всех завершённых заданий кампании на начало сборки отчёта находится в campaign_job_costs_at_report_start.csv; '
        'текущее задание отчёта там ещё не завершено. Подготовка, компиляции, ограниченные CP-поиски, ошибки и остановки '
        'входят в общий72runner-часовой бюджет; первичные выпуски и журналы Actions сохраняют их отдельно.',
        f'Невыполненных обязательств: {len(missing)}.']
    (ROOT/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    if not complete:raise ValueError('full inverse certification campaign remains incomplete')
