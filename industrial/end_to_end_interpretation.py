"""Render a readable interpretation of the immutable completed cost campaign."""
import csv
import os
from pathlib import Path
import shutil
from .common import actions_only,read_json,write_json
from .releases import fetch


def span(values,digits=3):
    lo,hi=min(values),max(values)
    return f'{lo:.{digits}f}' if lo==hi else f'{lo:.{digits}f}–{hi:.{digits}f}'


def main():
    actions_only()
    source=read_json('provenance/end_to_end_result.json')
    folder,receipt=fetch(source['report_release'],'output/end-to-end-interpretation-input')
    result=read_json(folder/'RESULT.json')
    if (result['status']!='COMPLETE' or result['commit']!=source['source_commit'] or
        result['observed_complete_processes']!=648 or result['observed_timeouts'] or
        result['observed_failed_or_invalid'] or result['scheduled_processes_without_available_record'] or
        len(result['rows'])!=108 or len(result['comparisons'])!=12 or
        result['verified_unique_failure_scenarios']!=6144):
        raise ValueError('complete comparable primary evidence is required')
    root=Path('output/end-to-end-interpretation');root.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(folder/'RESULT.json',root/'PRIMARY_RESULT.json')
    conditions=[];runtime_slower=0;first_use_slower=0
    for condition in result['comparisons']:
        if len(condition['runners'])!=3:raise ValueError('missing runner')
        answers=[];s1=[];direct=[];control=[];s1_cold=[];direct_cold=[];ratios=[];cold_ratios=[]
        for host in condition['runners']:
            rows=host['rows'];a,b,c=rows['s1_simpat'],rows['dag_direct'],rows['dag_simpat']
            if a['answer']!=b['answer'] or a['answer']!=c['answer']:raise ValueError('different useful result')
            answers.append(a['answer'])
            s1.append(a['median_s']);direct.append(b['median_s']);control.append(c['median_s'])
            s1_cold.append(a['first_use_total_s']);direct_cold.append(b['first_use_total_s'])
            ratios.append(a['median_s']/b['median_s'])
            cold_ratios.append(a['first_use_total_s']/b['first_use_total_s'])
            runtime_slower+=a['median_s']>b['median_s']
            first_use_slower+=a['first_use_total_s']>b['first_use_total_s']
        if any(a!=answers[0] for a in answers):raise ValueError('runner changed statistical population')
        conditions.append(dict(instance=condition['instance'],plan=condition['plan'],law=condition['law'],
            answer=answers[0],s1=s1,direct=direct,control=control,
            s1_first_use=s1_cold,direct_first_use=direct_cold,ratios=ratios,first_use_ratios=cold_ratios))
    total_hosts=sum(len(c['runners']) for c in result['comparisons'])
    verdict=result['verdict'];wins=[c for c in result['comparisons'] if c['measured_advantage']]
    lines=['# Виртуальные краш-тесты: результат полного сравнения','',
        '**Сравнение завершено: 648 из 648 процессов, без вычислительных ошибок и тайм-аутов.**',
        'В эти 648 входят прогревы; для статистической вероятности остаются 1024 независимых сценария на условие.','']
    if verdict=='NO_ESTABLISHED_ADVANTAGE':
        lines+=['**Преимущество S1/SIMPAT по зафиксированному критерию не установлено.**',
            f'В {runtime_slower} из {total_hosts} пар «условие / runner» медианное время запроса S1 больше времени прямого расчёта.',
            f'С учётом начальной подготовки это верно в {first_use_slower} из {total_hosts} пар.']
    else:
        lines+=['Измеренное преимущество ограничено следующими заранее заданными условиями:',
                ', '.join(f'{c["instance"]}/{c["plan"]}/{c["law"]}' for c in wins)+'.']
    lines+=['',
        'Проверялась полная процедура: входной план и условия → новые календари отказов → виртуальное исполнение → вероятность выполнить всю партию к сроку и доверительный интервал.',
        'Готовые журналы не предоставлялись бесплатно одному участнику. Каждый свежий измеряемый процесс сам генерировал воздействия и выполнял расчёт.',
        'Две реализации дали одинаковые исходы и оценки. При полных результатах исполнения обе оценки являются одной и той же частотой успеха; новая серия сравнивала стоимость её получения.','',
        'Прямая альтернатива использует технологические зависимости, фиксированные очереди станков и календари доступности. Такой профиль допускает расчёт без временной сетки.',
        'S1 использует исходное графовое ядро с адаптером операций. Полученные коэффициенты относятся к этим реализациям, включая языки и программную среду.','',
        '## Полная стоимость установленной программы','',
        'Основная сравниваемая стоимость — полное истёкшее время. CPU и отдельные post-exec пики памяти сохранены в первичных данных; сумма пиков двух процессов является верхней границей, а не измеренным совместным пиком.',
        'Время включает запуск нового процесса, импорты, проверку входа, генерацию и запись воздействий, native-подготовку и исполнение, подсчёт либо сокращение SIMPAT, доверительный расчёт и сохранение ответа.',
        'Диапазон в ячейке — минимум и максимум трёх медиан по разным runner. Каждая медиана получена из пяти процессов после отдельного прогрева. Отношения вычисляются внутри одного runner; значение больше 1 означает более долгий расчёт S1.','',
        '| Задача | План | Закон | S1/SIMPAT, с | Прямой расчёт, с | DAG/SIMPAT, с | S1 / прямой |',
        '|---|---|---|---:|---:|---:|---:|']
    for c in conditions:
        name='исходный' if c['plan']=='original' else 'CP-SAT'
        lines.append(f'| {c["instance"]} | {name} | {c["law"]} | {span(c["s1"])} | {span(c["direct"])} | {span(c["control"])} | {span(c["ratios"],2)} |')
    lines+=['',
        'DAG/SIMPAT использует тот же быстрый исполнитель, что и прямая альтернатива. Этот контроль отделяет расходы сокращённого вероятностного представления от расходов ядра S1. Он не обозначается результатом исполнения ядром TSFG.','',
        '## Первое использование с начальной подготовкой','',
        'К запросу добавлены измеренные установка общего окружения, получение замороженных входов и сборка конкретного участника. Для S1 также учтены окно установки Go и получение исходников S1.',
        'Компиляция независимых проверяющих движков, квалификация и отчёты входят в бюджет кампании, но не начисляются только одному участнику. Указана первоначальная подготовка опубликованной среды, а не минимальная теоретическая установка.','',
        '| Задача | План | Закон | S1: подготовка + запрос, с | Прямой: подготовка + запрос, с | S1 / прямой |',
        '|---|---|---|---:|---:|---:|']
    for c in conditions:
        name='исходный' if c['plan']=='original' else 'CP-SAT'
        lines.append(f'| {c["instance"]} | {name} | {c["law"]} | {span(c["s1_first_use"])} | {span(c["direct_first_use"])} | {span(c["first_use_ratios"],2)} |')
    lines+=['','## Что показали сами краш-тесты планов','',
        'Оба способа получили следующие одинаковые оценки. Производственный срок и станки одинаковы у исходного плана и CP-SAT; масштаб законов остаётся привязанным к исходному C0. CP-SAT-планы зафиксированы до этой новой серии.',
        'В скобках — 95%-й интервал Клоппера—Пирсона для отдельного условия. Одновременная гарантия для всей таблицы не заявляется.','',
        '| Задача | План | Закон | Успехи / испытания | Вероятность, % | 95%-й интервал, % |',
        '|---|---|---|---:|---:|---:|']
    for c in conditions:
        a=c['answer'];name='исходный' if c['plan']=='original' else 'CP-SAT';lo,hi=a['ci95']
        lines.append(f'| {c["instance"]} | {name} | {c["law"]} | {a["successes"]}/{a["samples"]} | {100*a["probability"]:.2f} | {100*lo:.2f}–{100*hi:.2f} |')
    lines+=['',
        'Это условные вероятности в виртуальных испытаниях при заданных законах отказов и ремонта. Реальная производственная история не использовалась. Совпадение реализаций не означает стопроцентной точности предсказания реального завода.',
        'Улучшение риска у плана CP-SAT относится к плану стандартного решателя; краш-тесты оценивают последствия отказов для каждого плана. Оно не доказывает превосходство способа оценки риска над прямым расчётом.',
        'S1/SIMPAT в этой постановке не получает статистического выигрыша от другого названия или представления той же суммы исходов. Результат не является универсальным отрицанием моделирования TSFG или его других целевых задач.','',
        '## Проверки и происхождение','',
        'Перед замерами проверены граничные случаи и полный вектор 1024 завершений каждого условия независимыми DES/DAG и обоими сокращёнными участниками.',
        'Первый запуск завершился ошибкой проверяющего кода до замеров: он не применял увеличение работы из сценария. Исправлена проверка строгого материального равенства; этот запуск и его затраты сохранены.',
        f'[Первичный отчёт и данные](https://github.com/a-a-k/industrial/releases/tag/{source["report_release"]}) · [Все задания Actions](https://github.com/a-a-k/industrial/actions/runs/{source["run_id"]})',
        'Исходники и бинарный файл закрытого ядра S1 не публикуются; его повтор требует разрешённого доступа к закреплённому исходнику. Открытые проверки и первичные результаты сохранены.']
    (root/'REPORT_RU.md').write_text('\n'.join(lines)+'\n')
    write_json(root/'INTERPRETATION.json',dict(status='COMPLETE',verdict=verdict,conditions=conditions,
        runtime_pairs_with_s1_slower=runtime_slower,first_use_pairs_with_s1_slower=first_use_slower,
        total_host_conditions=total_hosts,primary_report=source,primary_archive_sha256=receipt['archive_sha256'],
        primary_result_copied_byte_exact=True,interpretation_commit=os.environ['GITHUB_SHA']))
    with (root/'comparison.csv').open('w',newline='') as stream:
        fields=['instance','plan','law','runner','s1_s','direct_s','dag_simpat_s','s1_first_use_s','direct_first_use_s']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for c in conditions:
            for index,runner in enumerate((1,2,3)):
                writer.writerow(dict(instance=c['instance'],plan=c['plan'],law=c['law'],runner=runner,
                    s1_s=c['s1'][index],direct_s=c['direct'][index],dag_simpat_s=c['control'][index],
                    s1_first_use_s=c['s1_first_use'][index],direct_first_use_s=c['direct_first_use'][index]))


if __name__=='__main__':main()
