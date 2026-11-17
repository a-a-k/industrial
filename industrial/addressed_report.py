"""All addressed decisions, external outcomes and conservative complete-cost gates."""
import csv
from pathlib import Path
from statistics import median
from .common import canonical,digest,read_json,write_json
from .addressed_repair import ROOT,cases,fingerprint,spec,stamp
from .inverse_conditions import save_plan
from .releases import fetch
from .statistics import lower,upper


def csv_file(path,rows):
    if not rows:return
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def validation_prep(r):
    p=r['preparation'];build=p['build'];compiled=sum(x['wall_s'] for x in build['validation_build']['records'])
    remainder=max(0.,r['wall_s']-sum(c['validation_wall_s'] for c in r['conditions']))
    return p['common_environment_s']+build['oracle_compile_s']+compiled+remainder


def common_train(r):
    p=r['preparation']
    return p['common_environment_s']+p['build']['oracle_compile_s']+r['acquisition_s']+r['input_prepare_s']+r['generation_s']


def outcome_row(case,c):
    return dict(case=case,mask=c['mask'],machines=';'.join(map(str,c['machines'])),machine_count=len(c['machines']),
        successes=c['successes'],samples=c['samples'],probability=c['probability'],lower=c['lower'],upper=c['upper'],
        status=c['status'],validation_wall_s=c['validation_wall_s'])


def compare_cell(r):
    cfg=spec();cell=r['training_cell'];train=cell['training'];by_mask={c['mask']:c for c in r['conditions']}
    common=common_train(train)+validation_prep(r);cp=train['preparation']['cp_environment_s'];M=cell['used_machines']
    rows=[];pairs=[];prefixes=[];blockers=[]
    for repeat,group in enumerate(train['results']):
        pair={}
        for method in ('lazy','scan','cheap'):
            answer=group[method];selected=answer['selected'];c=by_mask[selected['mask']];warm=answer['process']['wall_s']
            full=common+(cp if method=='lazy' else 0.)+warm+c['validation_wall_s']
            pair[method]=dict(mask=c['mask'],k=len(c['machines']),status=c['status'],warm=warm,full=full,
                incumbent_complete=answer['incumbent_complete'],training_minimum_proved=answer['search']['minimum_proved'])
            rows.append(dict(case=r['case'],repeat=repeat,method=method,mask=c['mask'],machines=';'.join(map(str,c['machines'])),
                k=len(c['machines']),probability=c['probability'],lower=c['lower'],upper=c['upper'],status=c['status'],
                installed_search_s=warm,complete_first_use_s=full,training_minimum_proved=answer['search']['minimum_proved'],
                search_status=answer['search']['status'],incumbent_complete=answer['incumbent_complete']))
        named=[];D=pair['lazy']
        for parent in ('scan','cheap'):
            answer=group[parent];launch=max(0.,answer['process']['wall_s']-answer['internal_wall_s'])
            for name,value in answer['controls'].items():
                c=by_mask[value['mask']];k=len(c['machines'])
                if name!='uniform' and k<=D['k'] and c['status'] in ('FEASIBLE','UNRESOLVED'):
                    blockers.append(dict(repeat=repeat,parent=parent,control=name,mask=c['mask'],status=c['status'],k=k))
                if name in ('load','slack','greedy','pair') and c['status']=='FEASIBLE' and 0<k<M:
                    warm=value['ready_wall_s']+launch
                    named.append(dict(method=parent+'/'+name,k=k,warm=warm,full=common+warm+c['validation_wall_s']))
        pair['named']=named;pairs.append(pair);prefixes.extend(dict(repeat=repeat,**item) for item in named)
    all_complete=all(p[m]['incumbent_complete'] for p in pairs for m in ('lazy','scan','cheap'))
    sparse=all(0<p['lazy']['k']<M for p in pairs)
    valid=all(p[m]['status']=='FEASIBLE' for p in pairs for m in ('lazy','scan','cheap'))
    resource_refs=[min([p['scan']['full'],p['cheap']['full']]+[c['full'] for c in p['named']]) for p in pairs]
    resource_warm=[min([p['scan']['warm'],p['cheap']['warm']]+[c['warm'] for c in p['named']]) for p in pairs]
    d_full=[p['lazy']['full'] for p in pairs];d_warm=[p['lazy']['warm'] for p in pairs]
    resource_win=(valid and sparse and all_complete and not blockers
        and all(p['lazy']['k']<min(p['scan']['k'],p['cheap']['k']) for p in pairs)
        and median(d_full)<=cfg['cost_comparable_ratio']*median(resource_refs)
        and median(d_warm)<=cfg['cost_comparable_ratio']*median(resource_warm))
    equal=all(p['lazy']['k']==p['scan']['k'] and p['cheap']['k']>=p['lazy']['k'] for p in pairs)
    cost_refs=[];cost_warm=[]
    for p in pairs:
        eligible=[p['scan']]
        if p['cheap']['k']==p['lazy']['k']:eligible.append(p['cheap'])
        eligible.extend(c for c in p['named'] if c['k']<=p['lazy']['k'])
        cost_refs.append(min(v['full'] for v in eligible));cost_warm.append(min(v['warm'] for v in eligible))
    cost_win=(valid and sparse and all_complete and not blockers and equal
        and median(d_full)<=cfg['cost_improvement_ratio']*median(cost_refs)
        and median(d_warm)<=cfg['cost_improvement_ratio']*median(cost_warm)
        and sum(a<b for a,b in zip(d_full,cost_refs))>=4 and sum(a<b for a,b in zip(d_warm,cost_warm))>=4)
    reliability=(sparse and all_complete and not blockers
        and all(p['lazy']['status']=='FEASIBLE' and p['scan']['status']=='INFEASIBLE' and p['cheap']['status']=='FEASIBLE'
            and p['lazy']['k']<=p['scan']['k'] and p['lazy']['k']<p['cheap']['k'] for p in pairs)
        and median(d_full)<=cfg['cost_comparable_ratio']*median(resource_refs)
        and median(d_warm)<=cfg['cost_comparable_ratio']*median(resource_warm))
    gate=dict(scientific_win=bool(resource_win or cost_win or reliability),resource_win=bool(resource_win),cost_win=bool(cost_win),
        reliability_win=bool(reliability),all5_sparse=bool(sparse),all5_incumbents_complete=bool(all_complete),
        all5_DBC_certified=bool(valid),named_control_blockers=blockers,complete_D_median_s=median(d_full),
        complete_reference_median_s=median(cost_refs),installed_D_median_s=median(d_warm),installed_reference_median_s=median(cost_warm),
        prefix_cost_scope='measured elapsed-ready lower bounds; output shutdown omitted, conservatively favourable to controls',
        decision_repetitions=pairs)
    return gate,rows,prefixes


def report(registry):
    cfg=spec();ROOT.mkdir(parents=True,exist_ok=True)
    source,receipt=fetch(registry['seal'],'output/addressed-report-seal');sealed=read_json(source/'seal.json')
    if sealed['status']!='SEALED' or sealed['implementation']!=fingerprint() or sealed['spec']!=cfg:raise ValueError('addressed report seal mismatch')
    if {r['case'] for r in sealed['records']}!=cases():raise ValueError('addressed report requires all20 sealed cases')
    cells={r['case']:r for r in sealed['records']};alpha=cfg['family_error']/(2*sealed['configurations'])
    if alpha!=sealed['one_sided_alpha']:raise ValueError('addressed predeclared statistical family changed')
    records=[];missing=[];seen=set()
    for index,tag in enumerate(registry['validations']):
        try:
            folder,rcpt=fetch(tag,f'output/addressed-validation-{index}');r=read_json(folder/'validation.json');key=r['case']
            if key not in cases() or key in seen or r['status']!='PASS' or r['implementation']!=fingerprint() or r['spec']!=cfg:
                raise ValueError('invalid or duplicate addressed validation')
            if r['seal_release']!=registry['seal'] or r['seal_receipt']['archive_sha256']!=receipt['archive_sha256']:
                raise ValueError('mixed addressed seals')
            if canonical(r['training_cell'])!=canonical(cells[key]):raise ValueError('addressed decisions changed after seal')
            required={v['mask'] for v in cells[key]['variants']}
            if {c['mask'] for c in r['conditions']}!=required or len(r['conditions'])!=len(required):raise ValueError('addressed variants missing')
            for c in r['conditions']:
                expected_variant=next(v for v in cells[key]['variants'] if v['mask']==c['mask'])
                if c['samples']!=cfg['validation_samples'] or c['analytic_mismatches']!=0 or c['mask'].bit_count()!=len(c['machines']):
                    raise ValueError('addressed physical scope changed')
                if c['machines']!=expected_variant['machines'] or c['origins']!=expected_variant['origins']:
                    raise ValueError('addressed interventions or decision origins changed')
                if abs(c['lower']-lower(c['successes'],c['samples'],alpha))>1e-12 or abs(c['upper']-upper(c['successes'],c['samples'],alpha))>1e-12:
                    raise ValueError('addressed confidence bounds changed')
                native=read_json(folder/'variants'/str(c['mask'])/'des/production.json')
                if sum(t is not None for t in native['finished_at'])!=c['successes']:raise ValueError('external production census changed')
                if c['des_process']['status']!='OK' or any(p['process']['status']!='OK' for p in c['dag_calls']+c['s1_calls']):
                    raise ValueError('addressed independent process failed')
                if sum(p['samples'] for p in c['dag_calls'])!=cfg['validation_samples'] or sum(p['samples'] for p in c['s1_calls'])!=cfg['s1_scalar_samples']:
                    raise ValueError('addressed independent scalar checks incomplete')
                full=read_json(folder/'variants'/str(c['mask'])/'full/checks.json')
                if full['status']!='PASS' or full['samples']!=cfg['full_trace_samples'] or full['mismatches']!=0:
                    raise ValueError('addressed full physical checks incomplete')
                status='FEASIBLE' if c['lower']>=cfg['target_probability'] else 'INFEASIBLE' if c['upper']<cfg['target_probability'] else 'UNRESOLVED'
                if c['status']!=status:raise ValueError('addressed status changed')
            seen.add(key);records.append(dict(validation_release=tag,validation_receipt=rcpt,**r))
        except Exception as error:missing.append(dict(release=tag,error=str(error)))
    missing.extend(dict(case=c,error='required addressed validation missing') for c in sorted(cases()-seen))
    outcomes=[];decisions=[];summaries=[];gates={};prefixes=[];interventions=[]
    for key,cell in cells.items():
        instance=cell['training']['instance'];dest=ROOT/'plans'/instance
        if not dest.exists():save_plan(dest,read_json(source/key/'schedule.json'))
    for r in sorted(records,key=lambda r:r['case']):
        key=r['case'];cell=r['training_cell'];gate,rows,pr=compare_cell(r);gates[key]=gate;decisions.extend(rows)
        prefixes.extend(dict(case=key,**p) for p in pr);outcomes.extend(outcome_row(key,c) for c in r['conditions'])
        by_mask={c['mask']:c for c in r['conditions']};used=cell['used_machines'];base=by_mask[0]
        data=read_json(source/key/'schedule.json');first=r['training_cell']['training']['results'][0]
        D=by_mask[first['lazy']['selected']['mask']];B=by_mask[first['scan']['selected']['mask']];C=by_mask[first['cheap']['selected']['mask']]
        valid_sparse=[c for c in r['conditions'] if c['status']=='FEASIBLE' and 0<len(c['machines'])<used]
        summary=dict(case=key,used_machines=used,baseline_probability=base['probability'],baseline_status=base['status'],
            lazy_machines=';'.join(map(str,D['machines'])),lazy_k=len(D['machines']),lazy_probability=D['probability'],lazy_lower=D['lower'],lazy_status=D['status'],
            scan_k=len(B['machines']),scan_status=B['status'],cheap_k=len(C['machines']),cheap_status=C['status'],
            certified_sparse_options=len(valid_sparse),scientific_win=gate['scientific_win'],resource_win=gate['resource_win'],cost_win=gate['cost_win'],
            complete_D_median_s=gate['complete_D_median_s'],complete_reference_median_s=gate['complete_reference_median_s'])
        summaries.append(summary);case=ROOT/'cases'/key;case.mkdir(parents=True)
        csv_file(case/'conditions.csv',[outcome_row(key,c) for c in r['conditions']]);write_json(case/'comparison.json',gate)
        for row in rows:
            for m in by_mask[row['mask']]['machines']:
                interventions.append(dict(case=key,repeat=row['repeat'],method=row['method'],machine=m,
                    original_raw_mean_repair=.1*data['nominal_makespan']/100,
                    required_raw_mean_repair=.1*data['nominal_makespan']*cfg['repair_multiplier']/100,
                    distribution='exponential before rounding upward to0.05; unchanged working-period mean'))
        lines=[f'# {key}: адресный ремонт','',f'Используемых станков: {used}. Исходная доля партий вовремя: {100*base["probability"]:.2f}%, статус {base["status"]}.',
            f'Научное преимущество по полному критерию: {gate["scientific_win"]}.',
            '', '## Все измеренные решения', '', '| Повтор | Стратегия | Станки | Число | Вовремя | Нижняя граница | Статус | Полная первая цена, s |',
            '|---:|---|---|---:|---:|---:|---|---:|']
        for row in rows:lines.append(f'| {row["repeat"]} | {row["method"]} | {row["machines"] or "нет"} | {row["k"]} | '
            f'{100*row["probability"]:.2f}% | {100*row["lower"]:.2f}% | {row["status"]} | {row["complete_first_use_s"]:.3f} |')
        lines+=['', 'lazy — совместный подбор точными запретами; scan — прямой перебор ниже лучшего дешёвого решения; cheap — одна дешёвая комбинация. '
            'Остальные станки сохраняют исходный ремонт. Назначения и очереди остаются исходными. Индексы станков начинаются с0.',
            'Вмешательство уменьшает заданное среднее экспоненциальной длительности ремонта ДО округления до25%. Доступность ресурсов и стоимость такого ускорения не измерялись.',
            'comparison.json сохраняет все условия строгого gate и причины блокировки. conditions.csv включает все уникальные наборы, в том числе неопределённые и недостаточные.',
            'Минимум на рабочем банке512 не является минимумом истинной вероятности. Полный gate требует все пять повторов, адресное0<k<M, '
            'подтверждённые физические исходы и сравнение с самостоятельным cheap и ранними именованными контролями.']
        if r['law']=='F2SI':lines+=['F2SI предполагает общие случайные инновации и собственные renewal-часы; адресное действие не моделирует неизменяемый внешний общий простой.']
        (case/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    for name,rows in [('conditions.csv',outcomes),('decisions.csv',decisions),('summary.csv',summaries),('named_costs.csv',prefixes),('interventions.csv',interventions)]:csv_file(ROOT/name,rows)
    budget=read_json('output/budget.json');csv_file(ROOT/'campaign_jobs_at_report_start.csv',budget['jobs'])
    complete=not missing and seen==cases() and len(outcomes)==sealed['configurations'];wins=[s['case'] for s in summaries if s['scientific_win']]
    result=dict(technical_status='COMPLETE' if complete else 'PARTIAL',scientific_verdict='ESTABLISHED_ON_REGISTERED_CASES' if complete and wins else 'NOT_ESTABLISHED',
        completed_cases=len(seen),required_cases=20,completed_configurations=len(outcomes),required_configurations=sealed['configurations'],
        winning_cases=wins,cases_with_certified_sparse_options=sum(s['certified_sparse_options']>0 for s in summaries),summaries=summaries,
        gates=gates,validations=records,missing=missing,seal_release=registry['seal'],seal_receipt=receipt,
        family_error=cfg['family_error'],one_sided_alpha=alpha,global_optimality_claimed=False,real_plant_validation=False,
        exclusive_TSFG_advantage_claimed=False,report_source_sha256=digest(Path('industrial/addressed_report.py').read_bytes()),
        cost_scope='one measured preparation/certification plus each of five measured search processes; named ready costs are conservative lower bounds',
        implementation=fingerprint(),spec=cfg,**stamp())
    write_json(ROOT/'RESULT.json',result)
    lines=['# Адресное усиление ремонта: результаты','',
        f'Технический статус: **{result["technical_status"]}**, {len(seen)}/20 случаев, {len(outcomes)}/{sealed["configurations"]} сочетаний.',
        f'Случаев с подтверждённым непустым адресным набором: {result["cases_with_certified_sparse_options"]}/20. '
        f'Случаев, прошедших полный сравнительный gate: {len(wins)}. Научный итог: **{result["scientific_verdict"]}**.',
        '', 'На выбранных станках среднее экспоненциальной длительности ремонта до округления уменьшается до25%; '
        'остальные станки, весь план, партия и срок сохраняются. Достаточность подтверждается нижней биномиальной границей>=95% '
        'с одновременным покрытием всего заранее зафиксированного семейства не ниже95%.',
        '', '| Случай | Исходно вовремя | Станков всего | Станки lazy, повтор0 | Число | Нижняя граница | Статус | scan / cheap | Научный gate | Подробности |',
        '|---|---:|---:|---|---:|---:|---|---|---|---|']
    for s in summaries:lines.append(f'| {s["case"]} | {100*s["baseline_probability"]:.2f}% | {s["used_machines"]} | {s["lazy_machines"] or "нет"} | '
        f'{s["lazy_k"]} | {100*s["lazy_lower"]:.2f}% | {s["lazy_status"]} | {s["scan_k"]} / {s["cheap_k"]} | {s["scientific_win"]} | [Отчёт](cases/{s["case"]}/REPORT_RU.md) |')
    lines+=['', 'Повтор0 показан для чтения; он не выбирался после проверки. В decisions.csv и сравнительном gate учитываются ВСЕ пять повторов.',
        'Сравнение включает полный сильный прямой перебор, самостоятельную дешёвую комбинацию, нагрузку/запасы, жадный выбор с обратным удалением и просмотром пар. '
        'Любой доступный дешёвый вариант с не большим числом станков и FEASIBLE или UNRESOLVED консервативно блокирует победу. '
        'При сравнении затрат учитывается самый дешёвый достаточный ранний ответ, а не только дорогая стадия доказательства минимума.',
        'Пять пар измеряют поиск на одном runner. Полная первая цена составлена из измеренной подготовки, генерации, каждого процесса поиска и независимой сертификации его набора. '
        'Дополнительно применён тот же порог к установленному поиску, чтобы общая подготовка не создавала преимущество. '
        'Это измерения данных запусков, а не95%-я гарантия скорости. Времена ранних именованных ответов — нижние оценки, выгодные контролям. '
        'Все задания, неудачные квалификации и общий72runner-часовой бюджет раскрыты в первичных выпусках и campaign_jobs_at_report_start.csv.',
        'F1 — независимые renewal-процессы. F2SI — явно условное причинное расширение F2 с общими инновациями и отдельными часами; '
        'оно не устанавливает реакцию реального предприятия на общие внешние простои.',
        'Совместная Boolean/CP-оптимизация — стандартный инструмент. Эксклюзивное преимущество TSFG/SIMPAT, глобальный минимум и экономическая достижимость ремонта не заявляются.',
        f'Невыполненных обязательств: {len(missing)}.']
    (ROOT/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    if not complete:raise ValueError('addressed acceptance campaign remains incomplete')
