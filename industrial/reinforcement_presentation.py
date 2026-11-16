"""Human-readable presentation of already sealed and independently checked results."""
import csv
from pathlib import Path
import shutil
from .common import actions_only,canonical,digest,read_json,write_json
from .releases import fetch

ROOT=Path('output/fixed-local')


def csv_file(path,rows):
    if not rows:return
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def describe(edit,base):
    if edit['kind']=='none':return 'Оставить исходный план без изменений.'
    if edit['kind']=='swap':
        m,k=edit['machine'],edit['slot'];a,b=base['queues'][m][k:k+2]
        return f'На станке {m} поменять соседние операции {a} и {b}: вместо {a} → {b} выполнить {b} → {a}.'
    i,m,k=edit['operation'],edit['target'],edit['slot'];old=base['operations'][i]['machine']
    return f'Перенести операцию {i} со станка {old} на совместимый станок {m}, в позицию {k} его очереди после удаления операции из прежней очереди.'


def verdict(record):
    if record['training']['answers']['D']['selected']['kind']=='none':return 'План оставлен без изменений'
    interval=record['paired_D_against']['N']['outer95']
    if interval[0]>0:return 'Польза правки подтверждена'
    if interval[1]<0:return 'Ухудшение подтверждено'
    return 'Эффект правки не установлен'


def comparison_classes():
    catalogue=read_json('provenance/comparison_classes.json')
    lines=['# Классы конкурирующих подходов и границы сравнения','',
        f'Публичные первичные документы проверены {catalogue["checked_at"]}. Коммерческие программы не запускались; '
        'демо-доступы, пробные лицензии и обращения к поставщикам не использовались.',
        '', 'Классы ниже являются нашей аналитической группировкой функций. Они пересекаются: один продукт может относиться к нескольким.', '',
        '| Класс | Что считается результатом | Как проверяется в этой серии |', '|---|---|---|',
        '| Номинальное планирование APS | Допустимое расписание под цели и ограничения | Общий сильный CP-вход; это подготовка, отдельно от проверки риска |',
        '| Сценарное перепланирование | Новый план после изменения вводных | Другой режим управления; равное сравнение требует одинакового права менять план во время исполнения |',
        '| Стохастический DES и Монте-Карло | Риск выпуска и сроков при случайных воздействиях | Одинаковые замороженные назначения/очереди, законы и полные партии; независимые DES/DAG и S1 |',
        '| Объяснение задержек | Цепочки ожиданий, нагрузка, резервы, ограничения | S использует нагрузку/резервы; T — наблюдаемые прямые задержки |',
        '| Анализ чувствительности и локальное усиление | Одно допустимое изменение с внешне проверенным эффектом | D/D-DAG, а также сильный прямой просмотр G; один каталог, общий seal и новый банк |',
        '', '## Что заявлено в первичных документах', '',
        '| Продукт / модуль | Функциональный класс | Заявленные возможности и источник | Уровень свидетельства | Что не установлено |',
        '|---|---|---|---|---|']
    for p in catalogue['products']:
        evidence='Описание и пример производителя' if p['evidence']=='manufacturer worked example' else 'Заявление производителя'
        lines.append(f'| {p["product"]} | {p["classes"]} | {p["claim"]} [Первичный источник]({p["url"]}) | {evidence} | {p["unknown"]} |')
    lines+=['', '«Не установлено» означает недостаточность данного публичного свидетельства, а не отсутствие функции в продукте. '
        'Слово «оптимальный» и точная временная шкала интерфейса сами по себе не доказывают глобальную оптимальность или точность прогноза.',
        'Из документированных возможностей следует, что оценка риска, наблюдаемые ограничения и проверка вариантов уже встречаются у других разработчиков. '
        'Это вывод из документации, а не результат испытания программ. Уникальность общей идеи виртуального краш-теста здесь не заявляется.',
        '', '## Как сравнивать без лицензий', '',
        'Документальное сравнение отвечает, какие функции публично заявлены и какой экспериментальный вопрос соответствует каждому классу. '
        'Количественный эксперимент отвечает на отдельный вопрос: какую внешнюю пользу даёт наш конкретный алгоритм относительно сильной воспроизводимой открытой реализации.',
        'В этой серии S/T/G являются открытыми алгоритмическими контролями, D-DAG — идентичной диагностической стратегией на другом движке. '
        'Они не объявляются копиями БФГ, Adeptik, ALINA или Simio. Их результаты не являются измеренной скоростью или качеством этих продуктов.',
        'Для прямого количественного сравнения требуется один исполняемый режим: зафиксированы ли назначения и очереди, разрешено ли перепланирование, '
        'как возобновляется работа после ремонта, какой совместный закон отказов задан, что является успехом всей партии и какие полные затраты включены. '
        'Без такого контракта вероятности отдельного заказа, частоты выпуска всей партии, квантили сроков и границы по неполным наблюдениям несопоставимы.',
        'Сайт производителя с рекламным временем расчёта не заменяет сопоставимый benchmark. Результаты открытого контроля не устанавливают превосходства '
        'над закрытым продуктом. Для российских разработок используются те же уровни свидетельств и та же граница вывода.',
        'Полные статистические и стоимостные результаты текущей серии находятся в REPORT_RU.md, RESULT.json и costs.csv. '
        'Даже подтверждённое улучшение конкретного плана не устанавливает преимущество диагностической стратегии над сильнейшим дешёвым контролем.']
    (ROOT/'COMPARISON_CLASSES_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def comparative_verdict(result,costmap):
    records={(r['instance'],r['law']):r for r in result['conditions']}
    contrasts=[c for r in result['conditions'] for c in r['paired_D_against'].values()]
    if len(contrasts)!=100 or any(c['status']!='OK' or c['samples']!=4096 for c in contrasts):
        raise ValueError('comparative verdict requires all 100 complete preregistered contrasts')
    positive=[c for c in contrasts if c['outer95'][0]>0];shadowed=[];unshadowed=[]
    for flag in result['measured_comparative_pairs']:
        i,l=flag['instance'],flag['law'];r=records[(i,l)];method=flag['implementation']
        alternatives=[m for m in ('S','G') if r['methods'][m]['plan']==r['methods']['D']['plan'] and
            costmap[(i,l,m)]['first_use_from_fixed_plan_wall_s']<costmap[(i,l,method)]['first_use_from_fixed_plan_wall_s']]
        (shadowed if alternatives else unshadowed).append(dict(flag,cheaper_same_plan_controls=alternatives))
    if positive or unshadowed:raise ValueError('comparative interpretation requires a fresh criterion review')
    statement='Преимущество диагностической стратегии по критерию лучшего внешнего результата при сопоставимой полной цене либо того же полезного результата дешевле сильных контролей не установлено.'
    verdict=dict(status='NOT_ESTABLISHED',statement=statement,complete_contrasts=len(contrasts),
        contrasts_including_zero=sum(c['outer95'][0]<=0<=c['outer95'][1] for c in contrasts),
        confirmed_pairwise_external_advantages=len(positive),shadowed_cost_flags=shadowed,
        s1_slower_than_same_policy_dag_conditions=sum(costmap[(i,l,'D')]['complete_process_wall_s']>
            costmap[(i,l,'D-DAG')]['complete_process_wall_s'] for i,l in records),
        scope='the frozen diagnostic strategy, edit catalogue and failure laws; not all possible virtual crash-test methods')
    write_json(ROOT/'VERDICT.json',verdict);return verdict


def present():
    result=read_json(ROOT/'RESULT.json')
    comparison_classes()
    source,receipt=fetch(result['seal_release'],'output/presentation-seal')
    if receipt['archive_sha256']!=result['seal_receipt']['archive_sha256']:raise ValueError('presentation seal changed')
    seal=read_json(source/'seal.json');sealed={(r['instance'],r['law']):r for r in seal['conditions']}
    records=sorted(result['conditions'],key=lambda r:(r['instance'],r['law']))
    if any(canonical(r['training'])!=canonical(sealed[(r['instance'],r['law'])]) for r in records):raise ValueError('presentation training changed')
    weakspots=[];table=[];costmap={(r['instance'],r['law'],r['method']):r for r in result['costs']}
    overall=comparative_verdict(result,costmap)
    for record in records:
        instance,law=record['instance'],record['law'];cell=instance+'-'+law
        base=read_json(source/cell/'input.json');a=record['training']['answers']['D'];edit=a['selected']
        d,n=record['methods']['D'],record['methods']['N'];contrast=record['paired_D_against']['N'];lo,hi=contrast['outer95']
        diagnosis=a['diagnosis'];failed=diagnosis['failed'];ncal=diagnosis['samples']
        ranking=sorted(a['sensitivity'],key=lambda r:(-r['rescued_failed'],r['machine']))
        case=ROOT/'cases'/cell;case.mkdir(parents=True,exist_ok=True)
        lines=[f'# {instance}, {law}: проверка небольшого исправления','',
            f'Исходный CP-план занимает {base["planned_makespan"]/100:g}; прежний срок {record["deadline"]/100:g}. '
            f'Машин {len(base["queues"])}; операций {len(base["operations"])}; состав партии сохранён.',
            '', '## Где план уязвим', '',
            f'В {ncal} калибровочных виртуальных прогонах исходный план сорвал срок {failed} раз. '
            'Выполненные ниже вмешательства диагностические: отдельный станок временно считался идеально доступным, а исходный план сохранялся.']
        if ranking:
            lines+=['','| Станок | Сколько исходных срывов исчезло бы без его простоев | Проверено неуспешных прогонов с его простоем до срока |',
                '|---|---:|---:|']
            for r in ranking:
                lines.append(f'| {r["machine"]} | {r["rescued_failed"]}/{failed} | {r["evaluated"]} |')
                weakspots.append(dict(instance=instance,law=law,machine=r['machine'],calibration_batches=ncal,
                    calibration_failed=failed,ideal_availability_rescues=r['rescued_failed'],evaluated_failed=r['evaluated'],
                    observed_direct_delay_ticks_sum=diagnosis['machine_direct'][r['machine']]))
        else:lines+=['','Диагностические вмешательства не потребовались: все калибровочные партии уложились в срок.']
        lines+=['', 'Эти числа не складываются в число срывов: один и тот же срыв может исчезнуть при разных вмешательствах. '
            'Идеальная доступность не является предлагаемой производственной правкой. Для F2 это вмешательство может нарушать структуру общего календаря и служит только проверкой чувствительности.',
            '', '### Наблюдаемые задержки операций', '',
            'Среднее ожидание ремонта после готовности плюс паузы обработки на одну неуспешную калибровочную партию, включая нулевые задержки. '
            'Это наблюдаемая связь, а не причинный эффект конкретной операции.', '',
            '| Операция | Заказ | Станок | Прямое ожидание ремонта и паузы |', '|---|---|---|---:|']
        delayed=sorted(range(len(base['operations'])),key=lambda i:(-diagnosis['operation_direct'][i],i))[:10]
        for i in delayed:
            o=base['operations'][i]
            lines.append(f'| {i} | {o["job"]} | {o["machine"]} | {diagnosis["operation_direct"][i]/(100*failed) if failed else 0:.2f} |')
        lines+=['', 'Сумма ожиданий разных операций не равна потерянному времени всей партии: задержки могут перекрываться и передаваться дальше.',
            '', '## Что предлагается изменить', '', describe(edit,base),
            'Технологические зависимости и относительные порядки остальных операций сохраняются. Номинальная длительность не увеличивается. '
            'Полный пересчёт затронутых времён и очередей сохранён в diff.json; это последствия указанной структурной правки.']
        change=read_json(source/cell/'D-diff.json');write_json(case/'diff.json',change)
        diffrows=[]
        for r in change['operations']:
            diffrows.append(dict(operation=r['operation'],**{'before_'+k:v for k,v in r['before'].items()},
                **{'after_'+k:v for k,v in r['after'].items()}))
        csv_file(case/'diff.csv',diffrows)
        for method in result['spec']['methods']:
            plan=read_json(source/cell/(method+'.json'))
            if digest(canonical(plan))!=record['training']['answers'][method]['schedule_sha256']:raise ValueError('presentation plan changed')
            write_json(case/'schedules'/(method+'.json'),plan)
            csv_file(case/'schedules'/(method+'.csv'),[{k:o[k] for k in ('id','job','machine','work','planned_start','planned_end')}
                for o in plan['operations']])
        lines+=['','## Что произошло на новых проверочных сценариях','',
            f'Исходный план: {n["successes"]}/{n["samples"]} партий вовремя ({100*n["probability"]:.2f}%). '
            f'Предложенное решение: {d["successes"]}/{d["samples"]} ({100*d["probability"]:.2f}%).',
            f'Разность: {100*contrast["difference"]:+.2f} процентного пункта; общая внешняя граница '
            f'[{100*lo:+.2f}; {100*hi:+.2f}] п.п. для семейства 100 сравнений.',
            f'**{verdict(record)}.**',
            '', 'Это независимые сценарии, созданные после фиксации всех решений серии. '
            'Разность относится к осуществимой правке, а не к диагностической отмене поломок.',
            '', '## Контрольные решения и цена', '',
            '| Метод | Партий вовремя | Полный вызов от готового плана, с | С нужными первичными сборками, с | Правка |',
            '|---|---:|---:|---:|---|']
        for method in result['spec']['methods']:
            c=costmap[(instance,law,method)];m=record['methods'][method]
            lines.append(f'| {method} | {m["successes"]}/{m["samples"]} | {c["complete_process_wall_s"]:.3f} | '
                f'{c["first_use_from_fixed_plan_wall_s"]:.3f} | {record["training"]["answers"][method]["selected"]["id"]} |')
        lines+=['', 'D — диагностика на исходном S1/SIMPAT; D-DAG — та же стратегия на прямом DAG; N — без правки; '
            'L — номинальная правка; S — нагрузка/резервы и прямые краш-тесты; T — трассовые задержки и краш-тесты; '
            'G — прямой просмотр всего допустимого каталога с отсевом на 64 сценариях и полными 512 для финалистов.',
            'Историческое построение исходного CP-плана не делает дополнительную диагностику дешевле. '
            'Оно указано отдельно в costs.csv; стоимость независимой проверки также является отдельной стоимостью кампании.',
            'Время измерено один раз для каждого метода на одном runner. Наблюдаемый порядок времён не является доказательством устойчивого ускорения.',
            'Индексы операций и станков начинаются с нуля. Во временных полях JSON/CSV используются ticks: 100 ticks = 1 исходная единица времени.']
        if diagnosis['example']:
            write_json(case/'delay-chain.json',diagnosis['example'])
            example=diagnosis['example']
            lines+=['', '## Пример распространения задержки', '',
                f'Первый по заранее заданному порядку неуспешный калибровочный прогон: {example["attempt"]}. '
                f'Первый неготовый заказ: {example["late_job"]}. Ниже операции его наблюдаемой цепочки ожиданий.', '',
                '| Операция | Станок | Ожидание предшественников | Дополнительная очередь | Ремонт после готовности | Паузы обработки | Готова к сроку |',
                '|---|---|---:|---:|---:|---:|---|']
            for p in example['parts']:
                lines.append(f'| {p["operation"]} | {p["machine"]} | {p["upstream_wait"]/100:.2f} | '
                    f'{p["machine_queue_wait"]/100:.2f} | {p["repair_wait"]/100:.2f} | {p["processing_pause"]/100:.2f} | '
                    f'{"да" if p["complete"] else "нет"} |')
            if example['links']:
                lines+=['', 'Передача ожидания: '+ '; '.join(f'{p["source"]} → {p["target"]} '
                    f'({"технологическая зависимость" if p["kind"]=="technology" else "очередь станка"})' for p in example['links'])+'.']
            lines+=['', 'Это наблюдаемая цепочка одного прогона, а не отдельная выборка или причинный эффект исправления. '
                'Время после срока не приписывается завершению. Четыре временные части не пересекаются внутри одной операции; '
                'их суммы по разным операциям нельзя трактовать как потерю времени всей партии. Полная запись сохранена в delay-chain.json.']
        (case/'CORRECTION_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        table.append(dict(instance=instance,law=law,baseline=n['probability'],corrected=d['probability'],
            delta=contrast['difference'],lo=lo,hi=hi,verdict=verdict(record),edit=describe(edit,base),case=cell))
    csv_file(ROOT/'weakspots.csv',weakspots)
    shutil.copyfile(ROOT/'REPORT_RU.md',ROOT/'TECHNICAL_REPORT_RU.md')
    positive=sum(r['verdict']=='Польза правки подтверждена' for r in table)
    negative=sum(r['verdict']=='Ухудшение подтверждено' for r in table)
    unchanged=sum(r['verdict']=='План оставлен без изменений' for r in table)
    lines=['# Результаты краш-тестов и локального усиления планов','',
        f'Серия **{result["status"]}**: проверено {result["completed_conditions"]} из 20 условий Mk01–Mk10/F1/F2.',
        '', '**'+overall['statement']+'**','',
        f'Польза осуществимой правки подтверждена в {positive} условиях; ухудшение — в {negative}. '
        f'В {unchanged} условиях метод оставил исходный план без изменений. '
        f'В остальных {len(table)-positive-negative-unchanged} эффект предложенной правки не установлен.',
        '', 'У каждого условия сначала был зафиксирован сильный CP-план. Затем краш-тесты показали уязвимые ресурсы '
        'и цепочки задержек, метод предложил не более одного переноса или одной перестановки, '
        'а новые независимые прогоны проверили выпуск всей партии к прежнему сроку.',
        '', '| Задача | Закон | Исходный план, вовремя | После правки | Изменение, п.п. | Вывод | Подробности |',
        '|---|---|---:|---:|---:|---|---|']
    for r in table:lines.append(f'| {r["instance"]} | {r["law"]} | {100*r["baseline"]:.2f}% | {100*r["corrected"]:.2f}% | '
        f'{100*r["delta"]:+.2f} | {r["verdict"]} | [Правка и слабые места](cases/{r["case"]}/CORRECTION_RU.md) |')
    lines+=['', 'В каждом подробном отчёте указаны конкретные станки и операции, смысл диагностических вмешательств, '
        'полный diff и действительные расписания JSON/CSV всех семи методов. Все условия опубликованы, включая отрицательные и нулевые результаты.',
        '', 'Сильные открытые контроли используют статическую нагрузку и резервы, прямые трассы и просмотр всего каталога. '
        'D-DAG выполняет ту же стратегию, что S1/SIMPAT. Его совпадение с D отделяет диагностический алгоритм от стоимости движка; '
        'дополнительная информация в полной наблюдаемой вероятности SIMPAT не заявляется.',
        f'Все {overall["complete_contrasts"]} сохранённых доверительных интервалов сравнений включают ноль. '
        f'Отметок экономии относительно отдельного более узкого контроля: {len(overall["shadowed_cost_flags"])}; '
        'в этих условиях S/G возвращают тот же физический план с меньшей стоимостью первого использования. '
        'Эти отметки не устанавливают преимущество над сильнейшими разумными контролями.',
        'Стоимость решения и необходимые первичные сборки находятся в costs.csv. Сравнительная польза стратегии '
        'не следует автоматически из улучшения относительно исходного плана. Полные 100 парных сравнений, '
        'общие доверительные границы и затраты находятся в RESULT.json и TECHNICAL_REPORT_RU.md.',
        'Наблюдаемая экономия при одинаковом неизменённом плане — результат о цене возврата того же решения, '
        'а не подтверждение полезности осуществимого усиления. Один замер не устанавливает устойчивое ускорение.',
        'Это синтетические производственные задачи с заданными законами поломок. Реальное предприятие и лицензионные продукты '
        'не проверялись. Результаты не устанавливают почти стопроцентную точность прогноза в реальном производстве.',
        f'Ошибки, тайм-ауты и невыполненные обязательства не считаются срывами производства. '
        f'В итоговом протоколе невыполненных обязательств: {len(result["missing"])}.']
    lines+=['', 'Отрицательный вывод относится к проверенной стратегии, заданному каталогу малых правок и законам отказов. '
        'Он не доказывает отсутствие любого эффекта или бесполезность виртуальных краш-тестов вообще.']
    registry=read_json('provenance/fixed_plan_reinforcement_runs.json')
    infrastructure=registry.get('infrastructure_anomalies',[])
    for issue in infrastructure:
        lines+=['', f'Служебный сбой GitHub: при запуске фиксации {issue["run"]} не появился runner; '
            f'API отмены возвратил HTTP 409. Фиксация успешно выполнена повторным запуском {issue["replacement_run"]}. '
            'Первое служебное задание позднее начало выполняться и было отменено как неиспользуемый дубликат. '
            'Оно не используется в проверочных результатах и не выполняло производственных симуляций. '
            'Это отдельный сбой планирования задания, а не срыв срока партии или тайм-аут вычислителя.']
    (ROOT/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write_json(ROOT/'presentation.json',dict(status=result['status'],conditions=table,seal_receipt=receipt,
        infrastructure_anomalies=infrastructure,scientific_verdict=overall,
        source_sha256=digest(Path('industrial/reinforcement_presentation.py').read_bytes()),
        claim='presentation of sealed results; no new selection, simulation or significance tests'))


if __name__=='__main__':actions_only();present()
