"""Separate reporting of the unchanged 300-second series and 1200-second repeats."""
import csv
import os
from pathlib import Path
from .common import actions_only,read_json,write_json
from .releases import fetch


def run():
    root=Path('output/timeout-supplement');root.mkdir(parents=True,exist_ok=True)
    profile=read_json('provenance/timeout_extension.json')
    primary,_=fetch(profile['original_report'],'output/extension-original-report')
    original=read_json(primary/'RESULT.json');original_measures=read_json(primary/'cost-measurements.json.gz')
    records=[];missing=[];rows=[]
    for index,case in enumerate(profile['cases']):
        name='measurement-extended-'+case['id'].replace(':','-')
        tag=f"{name}-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
        try:
            source,receipt=fetch(tag,f'output/extension-new-{index}')
            measured=read_json(source/'measurement.json');ext=measured['timeout_extension']
            if (measured['case']!=case['id'] or measured['process_timeout_s']!=1200
                    or measured['observation_release']!=case['observations'] or measured['fit_release']!=case['fit']
                    or ext['parent_release']!=case['parent'] or not ext.get('exact_replay')):
                raise ValueError('extended case does not match its frozen profile')
            records.append(dict(release=tag,archive_sha256=receipt['archive_sha256'],**measured))
        except Exception as error:missing.append(dict(case=case['id'],release=tag,error=str(error)))
    obtained={m['case'] for m in original_measures if m['status']=='COMPLETE'}
    obtained.update(m['case'] for m in records if m['status']=='COMPLETE')
    complete=len(records)==2 and all(m['status']=='COMPLETE' for m in records) and not missing
    result=dict(status='COMPLETE' if complete else 'PARTIAL',
        original_report=profile['original_report'],original_protocol_status=original['status'],
        original_protocol_status_unchanged=True,original_timeout_s=300,extended_timeout_s=1200,
        original_method_timeouts=original['counters']['measurement_timeouts'],
        completed_extended_cases=sum(m['status']=='COMPLETE' for m in records),required_extended_cases=2,
        extended_attempts=sum(len(m['attempts']) for m in records),
        extended_timeouts=sum(r['status']=='TIMEOUT' for m in records for r in m['attempts']),
        extended_failures=sum(r['status']=='FAILED' for m in records for r in m['attempts']),
        extended_unrun=sum(max(0,12-len(m['attempts']))+sum(r['status']=='JOB_BUDGET_UNRUN' for r in m['attempts']) for m in records)
            +12*(2-len(records)),
        cost_cases_with_full_outputs_after_extension=len(obtained),required_cost_cases=original['cost_cases_required'],
        times_from_different_limits_pooled=False,missing=missing,
        completed_runner_hours_before_supplement=read_json('output/budget.json')['completed_s']/3600,
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(root/'RESULT.json',result);write_json(root/'measurements.json.gz',records)
    write_json(root/'profile.json',profile)
    for measurement in records:
        for method,summary in measurement['summary'].items():
            rows.append(dict(case=measurement['case'],status=measurement['status'],method=method,**summary,
                timeout_s=1200,shared_setup_s=measurement['shared_setup_s'],
                all_attempts_wall_s=sum(r.get('process',{}).get('wall_s',0) for r in measurement['attempts'] if r['method']==method),
                median_paired_ratio=measurement['median_paired_ratio']))
    if rows:
        with (root/'costs.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=['# Повторы вычислительных тайм-аутов','',f"Статус дополнения: **{result['status']}**.",'',
        'Два ранее цензурированных случая повторены при одинаковом для обоих методов лимите 1200 секунд. '
        'Входные gzip-журналы и контракты проверены на точное совпадение с прежними файлами до запуска методов. '
        'Сохранены один прогрев и пять измеряемых свежих процессов на метод, одно ядро, 4 GiB и один runner на пару.',
        '',f"Исходная серия с пределом 300 секунд сохраняет статус **{original['status']}** и все "
        f"{result['original_method_timeouts']} тайм-аутов. Времена разных лимитов не объединяются в однородную выборку.",
        '', '| Случай | Метод | Статус | Завершено из 5 | Медиана, с | CPU, с | RSS, MiB | Байты | Отношение первого / второго |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|']
    def fmt(x,d=3):return '—' if x is None else f'{x:.{d}f}'
    for row in rows:
        rss=row['median_peak_rss_bytes']
        lines.append(f"| {row['case']} | {row['method']} | {row['status']} | {row['completed']} / 5 | "
            f"{fmt(row['median_wall_s'])} | {fmt(row['median_cpu_s'])} | {fmt(None if rss is None else rss/1024**2)} | "
            f"{fmt(row['median_representation_bytes'],0)} | {fmt(row['median_paired_ratio'],4)} |")
    lines += ['',f"После дополнения полные результаты доступны для {len(obtained)} из {original['cost_cases_required']} обязательных случаев. "
        'Это наличие результатов при двух явно указанных лимитах, а не пересмотр статуса исходного протокола.',
        f"В дополнении: попыток {result['extended_attempts']}, тайм-аутов {result['extended_timeouts']}, "
        f"ошибок {result['extended_failures']}, незапущенных {result['extended_unrun']}.",
        'costs.csv сохраняет подготовку отдельно и суммарные времена всех попыток, включая прогревы. '
        'Все старые неудачные попытки, новые подготовки, проверки и повторы включены в общий runner-бюджет.',
        f"До запуска задания дополнения использовано {result['completed_runner_hours_before_supplement']:.3f} из 72 runner-часов.",
        '', '[Исходная сводка](https://github.com/a-a-k/industrial/releases/tag/'+profile['original_report']+').']
    for item in missing:lines.append('- '+str(item))
    (root/'REPORT_RU.md').write_text('\n'.join(lines)+'\n')
    print(result)


if __name__=='__main__':actions_only();run()
