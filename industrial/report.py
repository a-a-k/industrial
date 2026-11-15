"""Evidence-only E1–E6 report generation on GitHub-hosted Actions."""
import argparse
import csv
import json
import os
from pathlib import Path
import statistics
import subprocess
from .common import actions_only,read_json,write_json
from .releases import fetch


def run(registry):
    root=Path('output/final-report');root.mkdir(parents=True,exist_ok=True)
    missing=[]
    def load(tag,name,key):
        try:
            folder,receipt=fetch(tag,'output/report-input-'+key)
            return read_json(folder/name),folder
        except Exception as error:
            missing.append(dict(release=tag,expected=name,error=str(error)));return None,None
    q,qroot=load(registry['qualification'],'qualification.json','qualification')
    p,proot=load(registry['preflight'],'preflight.json','preflight')
    e,eroot=load(registry['evaluation'],'evaluation.json','evaluation')
    revision,revision_root=load(registry['analysis_revision'],'revision.json','analysis-revision')
    preparation_proof=None
    if registry.get('preparation_revision'):
        preparation_proof,_=load(registry['preparation_revision'],'qualification.json','preparation-revision')
    retired_preparations=[]
    for index,tag in enumerate(registry.get('superseded_preparations',[])):
        value,_=load(tag,'measurement.json',f'old-preparation-{index}')
        if value is not None:
            retired_preparations.append(dict(release=tag,**value))
            if value['preparation']['status']!='TIMEOUT' or value['attempts']:
                missing.append(dict(release=tag,error='only preparation timeouts with no method attempts may be replaced'))
    measures=[]
    for index,tag in enumerate(registry['measurements']):
        value,folder=load(tag,'measurement.json',f'measure-{index}')
        if value is not None:measures.append(dict(release=tag,**value))
    spec=read_json('provenance/measurements.json');required=[]
    for condition in spec['conditions']:
        for mode in spec['observation_modes']:
            for count in spec['loads']:
                for query,pairs in spec['pairs'].items():
                    for pair in pairs:required.append(f'{condition}:{mode}:{count}:{query}:{"-".join(pair)}')
            for pair in spec['saved_R_pairs']:required.append(f'{condition}:{mode}:512:saved_R:{"-".join(pair)}')
    required.append(spec['small_model_control']['case'])
    by_case={m['case']:m for m in measures}
    new_preparation=[m for m in measures if m.get('preparation_qualification')]
    preparation_accepted=not new_preparation or (preparation_proof is not None and preparation_proof['status']=='PASS'
        and all(m['preparation_qualification']==registry.get('preparation_revision') for m in new_preparation))
    if not preparation_accepted:missing.append(dict(error='revised replay preparation lacks its exact-byte qualification'))
    final_solver=read_json('provenance/analysis_compatibility.json')['new_sha256']
    for m in measures:
        if m.get('analysis_source_sha256')!=final_solver:
            missing.append(dict(case=m['case'],error='cost case uses a superseded analysis version'))
    for case in required:
        if case not in by_case:missing.append(dict(case=case,error='required cost case unavailable'))
    if len(by_case)!=len(measures):missing.append(dict(error='duplicate cost case registry'))
    if set(by_case)-set(required):missing.append(dict(error='undeclared cost cases'))
    budget=read_json('output/budget.json')
    blocks=dict(E1='PASS' if q and q['status']=='CORE_PASS' and p and p['status']=='PASS' else 'PARTIAL',
        E2='PASS' if q and q['status']=='CORE_PASS' else 'PARTIAL',
        E3='PASS' if q and q['status']=='CORE_PASS' and p and p['status']=='PASS' and revision and revision['status']=='PASS' else 'PARTIAL',
        E4='PASS' if e and len(e['fit_statuses'])==20 and len(e['validation_reanalysis_statuses'])==20
            and all(v=='PASS' for v in [*e['fit_statuses'].values(),*e['validation_reanalysis_statuses'].values()]) else 'PARTIAL',
        E5='PASS' if e and e['status']=='PASS' else 'PARTIAL',
        E6='PASS' if len(by_case)==len(required) and all(m['status']=='COMPLETE' for m in measures) and preparation_accepted else 'PARTIAL')
    status='COMPLETE' if all(v=='PASS' for v in blocks.values()) and not missing else 'PARTIAL'
    banks=e['banks'] if e else []
    counters=dict(stochastic_registered=sum(b['registered'] for b in banks),
        des_completed=sum(b['des_completed'] for b in banks),dag_completed=sum(b['dag_completed'] for b in banks),
        tsfg_required=sum(b['tsfg_required'] for b in banks),tsfg_completed=sum(b['tsfg_completed'] for b in banks),
        engine_mismatches=sum(len(b['mismatches']) for b in banks),
        production_timeouts=sum(pr['status']=='TIMEOUT' for b in banks for pr in b['processes']),
        measurement_processes=sum(len(m['attempts']) for m in measures),
        measurement_timeouts=sum(a['status']=='TIMEOUT' for m in measures for a in m['attempts']),
        measurement_failed=sum(a['status']=='FAILED' for m in measures for a in m['attempts']),
        measurement_unrun=sum(a['status']=='JOB_BUDGET_UNRUN' for m in measures for a in m['attempts'])
            +sum(max(0,12-len(m['attempts'])) for m in measures),
        preparation_timeouts=sum(m['preparation']['status']=='TIMEOUT' for m in measures),
        preparation_failed=sum(m['preparation']['status'] not in ('OK','SAVED_MODEL','TIMEOUT') for m in measures),
        superseded_preparation_timeouts=sum(m['preparation']['status']=='TIMEOUT' for m in retired_preparations))
    elapsed=budget['completed_s']/3600
    result=dict(status=status,blocks=blocks,counters=counters,missing=missing,registry=registry,
        cost_cases_required=len(required),cost_cases_available=len(by_case),
        cost_cases_complete=sum(m['status']=='COMPLETE' for m in measures),
        completed_runner_hours_before_report=elapsed,runner_hour_limit=72,
        report_reservation_hours=1.5,monetary_budget=0,commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    forecast_summary=[]
    if e:
        for direction,law,regime in (('F1_to_F1','F1','same_regime'),
                ('F1_to_F2_frozen','F2','frozen_F1_to_F2'),('F2_to_F2_refit','F2','same_regime')):
            for mode in ('available','mcar10','mcar30','informative','trace_loss'):
                selected=[r for r in e['forecasts'] if r['status']=='OK' and r['deadline_label']=='110'
                    and r['target']=='execution' and r['regime']==regime
                    and r['condition'].endswith(law) and r['mode']==mode]
                points=[r for r in selected if r['signed_error'] is not None]
                forecast_summary.append(dict(direction=direction,mode=mode,conditions=len(selected),point_rows=len(points),
                    point_mean_absolute_error=statistics.mean(r['absolute_error'] for r in points) if points else None,
                    point_mean_signed_error=statistics.mean(r['signed_error'] for r in points) if points else None,
                    median_identification_width=statistics.median(r['prediction_width'] for r in selected) if selected else None,
                    discrepancy_outer95_excludes_zero=sum(r['discrepancy_outer95'][0]>0 or r['discrepancy_outer95'][1]<0 for r in selected)))
    result.update(forecast_accuracy_implied_by_block_PASS=False,
        global_forecast_coverage_claimed=False,forecast_summary_scope='descriptive; primary deadline 110, execution target, ten instances per row')
    write_json(root/'RESULT.json',result)
    write_json(root/'forecast-summary.json',forecast_summary)
    write_json(root/'registry.json',registry)
    write_json(root/'cost-measurements.json.gz',measures)
    write_json(root/'superseded-preparations.json.gz',retired_preparations)
    if preparation_proof is not None:write_json(root/'preparation-revision.json',preparation_proof)
    if revision is not None:write_json(root/'analysis-revision.json',revision)
    if e is not None:write_json(root/'evaluation.json.gz',e)
    # Preserve failed infrastructure jobs independently from scientific result status.
    raw=subprocess.check_output(['gh','api','--paginate',f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/runs?per_page=100',
        '--jq','.workflow_runs[] | {id,head_sha,status,conclusion,html_url,created_at,updated_at}'],text=True)
    (root/'workflow-history.jsonl').write_text(raw)
    cost_fields=['case','status','method','required','completed','timeouts','completion_fraction',
        'median_wall_s','median_completed_only_diagnostic_s','median_cpu_s','median_peak_rss_bytes','median_representation_bytes',
        'shared_setup_s','preparation_status','preparation_encoding','preparation_qualification',
        'method_all_attempts_wall_s','pair_with_setup_wall_s']
    with (root/'costs.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=cost_fields);writer.writeheader()
        for m in measures:
            for method,summary in m['summary'].items():
                wall=lambda row:row.get('process',{}).get('wall_s',0)
                writer.writerow(dict(case=m['case'],status=m['status'],method=method,**summary,
                    shared_setup_s=m['shared_setup_s'],preparation_status=m['preparation']['status'],
                    preparation_encoding=(m.get('load') or {}).get('encoding_version','original'),
                    preparation_qualification=m.get('preparation_qualification',''),
                    method_all_attempts_wall_s=sum(wall(r) for r in m['attempts'] if r['method']==method),
                    pair_with_setup_wall_s=m['shared_setup_s']+sum(wall(r) for r in m['attempts'])))
    if eroot is not None:
        import shutil
        shutil.copyfile(eroot/'forecasts.csv',root/'forecasts.csv')
    lines=['# Производственные наблюдения: E1–E6','',f'Статус серии: **{status}**.','',
        'Единица испытания — исполнение всей фиксированной партии. Три срока и повторные маски не увеличивают число независимых репликаций.',
        '', '| Блок | Статус |','|---|---|']
    lines += [f'| {name} | {value} |' for name,value in blocks.items()]
    lines += ['', '## Производственный банк','',
        f"Зарегистрировано стохастических сценариев: {counters['stochastic_registered']} из 30 720. "
        f"DES завершил {counters['des_completed']}; DAG — {counters['dag_completed']}. "
        f"TSFG завершил {counters['tsfg_completed']} из требуемых {counters['tsfg_required']} стохастических траекторий.",
        f"Расхождения движков: {counters['engine_mismatches']}. Вычислительные тайм-ауты производственных процессов: {counters['production_timeouts']}."]
    if p:
        lines += ['', '| Экземпляр | Заказы | Операции | Координаты | Безотказный C0 |', '|---|---:|---:|---:|---:|']
        lines += [f"| {r['instance']} | {r['jobs']} | {r['operations']} | {r['coordinates']} | {r['nominal_makespan']/100:g} |" for r in p['instances']]
    if q:
        lines += ['',f"Квалификация: {q['tests']} тестов, ошибок {q['errors']}, неудач {q['failures']}, пропусков {q['skipped']}. "
            'Проверены независимые конечные состояния, совместные векторы целей, полные свидетели, временные границы и изолированное воспроизведение.']
    if revision:
        lines += ['',f"Квалифицирована эквивалентная версия построения сертификатов: {len(revision['exact_scalar_comparisons'])} "
            f"сравнений точных старых/новых границ; {len(revision['retained_old_comparisons'])} сохранённых старых случаев совпали также по хешам входа и модели; "
            f"повторно проверено максимальных схем: {len(revision['maximum_schemas'])}. "
            'Все двадцать калибровочных моделей пересчитаны одной версией до открытия проверочных исходов. '
            'Заменённые расчёты и их затраты сохранены отдельно и включены в общий бюджет кампании.']
    lines += ['', '## Независимый прогноз','',
        'Модели определены по 512 калибровочным попыткам на условие и закреплены до получения 1024 проверочных исходов. '
        'F1→F1, F1→F2 без переидентификации и переидентификация F2→F2 представлены отдельно. '
        'Структура, привязки и декартово семейство в E5 фиксированы.']
    if e:
        checks=e['calibration_checks']
        lines += [f"Точное совпадение полных доступных оценок E/R с независимой калибровочной частотой: "
                  f"{sum(c['status']=='PASS' for c in checks)} из 60 проверок. Строк проверки прогноза: {e['completed_forecast_rows']} из 900.",
            f"По каждой попытке выполнено сопоставление внешнего результата с границами E/R: "
            f"{sum(c['status']=='PASS' for c in e['external_event_checks'])} из 40 банков. "
            'Повторные сроки, маски и цели в этих проверках не увеличивают статистическую выборку.',
            '', '| Экземпляр | Закон проверки | Модель | Прогноз E | Частота проверки | Знаковая ошибка |', '|---|---|---|---:|---:|---:|']
        for row in e['forecasts']:
            if row['status']=='OK' and row['deadline_label']=='110' and row['mode']=='available' and row['target']=='execution':
                prediction=row['prediction'];point=f'{prediction[0]:.6f}' if prediction[0]==prediction[1] else f'[{prediction[0]:.6f}; {prediction[1]:.6f}]'
                err='—' if row['signed_error'] is None else f'{row["signed_error"]:+.6f}'
                lines.append(f"| {row['condition'][:4]} | {row['condition'][-2:]} | {row['source_condition'][-2:]} | {point} | {row['validation_frequency']:.6f} | {err} |")
    lines += ['', 'Доверительные области относятся к отдельным условиям. Для вероятности используются биномиальные счётчики гарантированных/возможных успехов; '
        'для расхождения — четыре односторонние границы 98,75%. Идентификационные и доверительные интервалы имеют разный смысл. '
        'Превосходство над калибровочной частотой не предполагается.',
        '', '| Направление | Наблюдения | Условий | Точечных оценок | MAE точек, п.п. | Медиана ширины, п.п. | Область расхождения не содержит 0 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for row in forecast_summary:
        mae='—' if row['point_mean_absolute_error'] is None else f"{100*row['point_mean_absolute_error']:.2f}"
        width='—' if row['median_identification_width'] is None else f"{100*row['median_identification_width']:.2f}"
        lines.append(f"| {row['direction']} | {row['mode']} | {row['conditions']} | {row['point_rows']} | {mae} | {width} | {row['discrepancy_outer95_excludes_zero']} |")
    lines += ['', 'Эта описательная сводка использует только основной срок 1,10 C0 и цель E. '
        'Число областей, не содержащих ноль, не имеет отдельной совместной гарантии для всей таблицы. '
        'PASS блока E5 означает выполнение обязательных вычислений и проверок, а не точность всех прогнозов. '
        'При потере записей границы могут стать широкими; изменение режима может потребовать переидентификации.',
        '', '## Вычислительные затраты','',
        f"Обязательных парных случаев: {len(required)}; получено {len(by_case)}; полностью завершено {result['cost_cases_complete']}. "
        f"Тайм-аутов: {counters['measurement_timeouts']}; ошибок процессов: {counters['measurement_failed']}; незапущенных повторов: {counters['measurement_unrun']}.",
        f"В итоговых случаях подготовки нагрузки: тайм-аутов {counters['preparation_timeouts']}; ошибок {counters['preparation_failed']}. "
        f"Отдельно сохранено предыдущих тайм-аутов подготовки до запуска методов: {counters['superseded_preparation_timeouts']}.",
        'Каждая пара выполнена на одном runner, в контейнере с одним ядром и лимитом 4 GiB. Один прогрев и пять измеряемых свежих процессов на метод. '
        'Прогревы и подготовка сохранены отдельно; времена тайм-аутов цензурированы. '
        'Медианы отношений публикуются только при пяти корректных завершённых парах. Повторённые журналы — нагрузка, не новые производственные испытания.',
        'Время в строке метода относится к одному свежему процессу. Общая подготовка показана отдельно; '
        'costs.csv также содержит суммарное время всех попыток, включая прогревы и цензурированные процессы, и стоимость пары с подготовкой. '
        'Установка окружения и сборки дополнительно учтены в полном runner-бюджете кампании.',
        '', '| Случай | Статус | Метод | Время, с | CPU, с | RSS, MiB | Представление, байт | Завершено из 5 | Отношение первого / второго |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|']
    def number(value,digits=4):return '—' if value is None else f'{value:.{digits}f}'
    for m in sorted(measures,key=lambda x:x['case']):
        ratio='—' if m['median_paired_ratio'] is None else f'{m["median_paired_ratio"]:.4f}'
        for method,s in m['summary'].items():
            rss=s.get('median_peak_rss_bytes')
            lines.append(f"| {m['case']} | {m['status']} | {method} | {number(s['median_wall_s'])} | "
                f"{number(s.get('median_cpu_s'))} | {number(None if rss is None else rss/1024**2,2)} | "
                f"{number(s.get('median_representation_bytes'),0)} | {s['completed']} / {s['required']} | {ratio} |")
    lines += ['', '| Случай | Подготовка и загрузка, с | Все процессы пары с подготовкой, с |', '|---|---:|---:|']
    for m in sorted(measures,key=lambda x:x['case']):
        total=m['shared_setup_s']+sum(r.get('process',{}).get('wall_s',0) for r in m['attempts'])
        lines.append(f"| {m['case']} | {m['shared_setup_s']:.3f} | {total:.3f} |")
    if preparation_proof is not None:
        lines += ['', 'Подготовка повторного журнала использует кэш канонических шаблонов. '
            'Квалификация подтвердила точные SHA-256 прежних gzip-файлов, обработку коллизий идентификатора '
            'и неизменность измеряемого метода и защищённых модулей. Лимит 300 секунд сохранён. '
            'Повторены только случаи, в которых прежняя подготовка завершилась тайм-аутом до запуска методов; '
            'старые измерения методов не заменялись. Затраты прежних подготовок, квалификации и повторов '
            'включены в общий runner-бюджет; версии подготовки указаны в costs.csv.']
    lines += ['', '## Границы выводов и невыполненные обязательства','',
        'Проверяется идентификация по синтетическим производственным наблюдениям. Данные реального оборудования и экономический выбор резерва не исследовались. '
        'Перенос относится к процедуре, а не к численным параметрам между разными экземплярами. Mk08–Mk10 ранее использовались в отдельном TSFG исследовании.',
        'Full-R, projection-R и direct-R математически эквивалентны в объявленном семействе. Совпадение — проверка реализации; '
        'изменение времени характеризует конкретные реализации при сохранённой цели. Combination сохраняет структурные запросы, которые direct-R отдельно не поддерживает.',
        f'До начала отчётного задания использовано {elapsed:.3f} runner-часа из 72. Денежный бюджет — ноль; стандартные публичные GitHub-hosted runners, без платного хранения.',
        'История заменённых предварительных проверок сохранена. Исправление календарных событий H выполнено до стохастического банка; прежний preflight не используется для приёмки.']
    for block,value in blocks.items():
        if value!='PASS':lines.append(f'- {block}: обязательные результаты не полностью приняты; подробности в RESULT.json и первичных выпусках.')
    for item in missing:lines.append('- '+json.dumps(item,ensure_ascii=False))
    lines += ['', '## Артефакты','',
        '[Протокол](https://github.com/a-a-k/industrial/blob/main/docs/PROTOCOL.md). '
        'Точные выпуски входов, моделей, проверок и измерений перечислены в registry.json. '
        'SHA256SUMS.json и receipts фиксируют файлы и их происхождение. Закрытые исходники и бинарник S1 не распространяются.',
        '', f"Исходный коммит отчёта: `{os.environ['GITHUB_SHA']}`; Actions run `{os.environ['GITHUB_RUN_ID']}`."]
    (root/'REPORT_RU.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    actions_only();parser=argparse.ArgumentParser();parser.add_argument('registry');args=parser.parse_args();run(read_json(args.registry))
