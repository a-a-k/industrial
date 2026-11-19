"""Read-only structural applicability census. All execution belongs to Actions."""
import csv
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import time

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Actions only')

START = time.perf_counter()
ROOT = Path.cwd()
OUT = ROOT / 'output/compositional-feasibility'
OUT.mkdir(parents=True, exist_ok=True)
SPEC = json.loads((ROOT / 'provenance/compositional_feasibility.json').read_text())
CHECKS = []


def check(name, condition):
    CHECKS.append(dict(name=name, passed=bool(condition)))
    if not condition:
        raise ValueError(name)


def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def topological(ops, edges):
    children = [set() for _ in ops]
    parents = [set() for _ in ops]
    for a, b in edges:
        children[a].add(b)
        parents[b].add(a)
    degree = [len(p) for p in parents]
    order = [i for i, d in enumerate(degree) if not d]
    for i in order:
        for j in sorted(children[i]):
            degree[j] -= 1
            if not degree[j]:
                order.append(j)
    check('acyclic', len(order) == len(ops))
    return order, parents, children


def windows(data, fixed, deadline):
    ops = data['operations']
    edges = {(p, o['id']) for o in ops for p in o['predecessors']}
    if fixed:
        edges |= {(a, b) for q in data['queues'] for a, b in zip(q, q[1:])}
    order, parents, children = topological(ops, edges)
    work = [o['work'] if fixed else min(a['work'] for a in o['alternatives']) for o in ops]
    earliest = [0] * len(ops)
    for i in order:
        o = ops[i]
        release = max(o['release'], data['jobs'][o['job']]['release'])
        if fixed:
            release = max(release, o['planned_start'])
        earliest[i] = max(release, max((earliest[p] + work[p] for p in parents[i]), default=0))
    latest = [deadline] * len(ops)
    for i in reversed(order):
        latest[i] = min(deadline, min((latest[j] - work[j] for j in children[i]), default=deadline))
    return earliest, latest, work, edges


def partition(weights, name):
    count = len(weights)
    if name == 'contiguous':
        return [4 * m // count for m in range(count)]
    if name == 'round_robin':
        return [m % 4 for m in range(count)]
    loads = [Fraction(0)] * 4
    members = [0] * 4
    result = [-1] * count
    for m in sorted(range(count), key=lambda m: (-weights[m], m)):
        b = min(range(4), key=lambda b: (loads[b], members[b], b))
        result[m] = b
        loads[b] += weights[m]
        members[b] += 1
    return result


def size(domains):
    cells = math.prod(domains)
    return dict(coordinates=len(domains), log2_cells=math.log2(cells),
                cells_bit_length=cells.bit_length(), cells_exact=str(cells),
                over_memory_8byte=cells * 8 > SPEC['dense_memory_budget_bytes'],
                over_memory_bitpacked=(cells + 7) // 8 > SPEC['dense_memory_budget_bytes'])


def census(data, name, fixed, reduced=False):
    ops = data['operations']
    delta = data['delta']
    domain_step = delta if fixed else math.gcd(*(a['work'] for o in ops for a in o['alternatives']))
    deadline = SPEC['deadline_numerator'] * data['nominal_makespan'] // SPEC['deadline_denominator']
    start, latest, work, edges = windows(data, fixed, deadline)
    domains = []
    for o in ops:
        i = o['id']
        first = (start[i] + domain_step - 1) // domain_step
        if fixed:
            count = latest[i] // delta - (start[i] + work[i] + delta - 1) // delta + 1
        else:
            count = sum(max(0, (latest[i] - a['work']) // domain_step - first + 1) for a in o['alternatives'])
        check('nonempty_necessary_domain', count > 0)
        domains.append(count)
    weights = [Fraction(0) for _ in data['queues']]
    for o in ops:
        if fixed:
            weights[o['machine']] += o['work']
        else:
            for a in o['alternatives']:
                weights[a['machine']] += Fraction(a['work'], len(o['alternatives']))
    block = partition(weights, name)
    check('four_nonempty_machine_blocks', set(block) == set(range(4)))
    scope_edges = set(edges)
    removed = set()
    if reduced:
        order, _, children = topological(ops, edges)
        reachable = [0] * len(ops)
        for i in reversed(order):
            for j in children[i]:
                reachable[i] |= (1 << j) | reachable[j]
        technological = {(p, o['id']) for o in ops for p in o['predecessors']}
        for a, b in technological:
            if block[ops[a]['machine']] == block[ops[b]['machine']]:
                continue
            if any(c != b and reachable[c] & (1 << b) for c in children[a]):
                removed.add((a, b))
        scope_edges -= removed
        new_order, _, new_children = topological(ops, scope_edges)
        new_reachable = [0] * len(ops)
        for i in reversed(new_order):
            for j in new_children[i]:
                new_reachable[i] |= (1 << j) | new_reachable[j]
        check('reduced_graph_preserves_all_reachability', reachable == new_reachable)
    scopes = [set() for _ in ops]
    if fixed:
        for o in ops:
            scopes[o['id']].add(block[o['machine']])
        for a, b in scope_edges:
            scopes[a].add(block[ops[b]['machine']])
    else:
        # Raw technological factors never use the frozen queues, assignments or planned starts.
        for o in ops:
            owner = 4 * o['job'] // len(data['jobs'])
            for i in (o['id'], *o['predecessors']):
                scopes[i].add(owner)
            for a in o['alternatives']:
                scopes[o['id']].add(block[a['machine']])
    boundary = [i for i, s in enumerate(scopes) if len(s) > 1]
    pairs = []
    for a in range(4):
        for b in range(a + 1, 4):
            pair_vars = [i for i in boundary if scopes[i] == {a, b}]
            pairs.append(dict(blocks=[a, b], variables=pair_vars, **size([domains[i] for i in pair_vars])))
    blocks = []
    for b in range(4):
        machines = [m for m, owner in enumerate(block) if owner == b]
        variables = [i for i in boundary if b in scopes[i]]
        envelope = math.prod(2 * (1 + sum(ops[i]['work'] // delta + 1 for i in data['queues'][m])) for m in machines) if fixed else None
        blocks.append(dict(block=b, machines=machines, boundary_operations=variables,
                           **size([domains[i] for i in variables]),
                           fixed_queue_progress_envelope_log2=math.log2(envelope) if fixed else None))
    # For four precomputed dense factors, a balanced contraction can select any
    # of the three distinct 2|2 cuts. This is a materialised-box peak, not an
    # arithmetic lower bound for sparse, streaming or signed representations.
    cuts = []
    for other in (1, 2, 3):
        left = {0, other}
        right = set(range(4)) - left
        variables = [i for i in boundary if scopes[i] & left and scopes[i] & right]
        cut = dict(left=sorted(left), right=sorted(right), variables=variables,
                   **size([domains[i] for i in variables]))
        cut['peak_log2_cells'] = max(cut['log2_cells'], max(b['log2_cells'] for b in blocks))
        cuts.append(cut)
    best_cut = min(cuts, key=lambda c: (c['peak_log2_cells'], c['left']))
    total_input_cells = sum(int(b['cells_exact']) for b in blocks)
    healthy = max(start[i] + work[i] for i in range(len(ops))) if fixed else None
    planned_redundant = all(o['planned_start'] == start[o['id']] for o in ops) if fixed else None
    # Verify redundancy by rebuilding earliest times without the supplied planned lower bounds.
    if fixed:
        order, parents, _ = topological(ops, edges)
        plain = [0] * len(ops)
        for i in order:
            plain[i] = max(ops[i]['release'], max((plain[p] + work[p] for p in parents[i]), default=0))
        planned_redundant = all(o['planned_start'] <= plain[o['id']] for o in ops)
        check('healthy_ends_inside_windows', all(start[i] + work[i] <= latest[i] for i in range(len(ops))))
    return dict(instance=data['dataset_id'],
                profile='fixed_reduced_execution' if reduced else 'fixed_execution' if fixed else 'raw_synthesis',
                removed_transitive_cross_edges=sorted(removed),
                partition=name, deadline_ticks=deadline, delta=delta, domain_step=domain_step,
                machines=len(data['queues']), operations=len(ops),
                blocks=blocks, pair_interfaces=pairs, boundary_operations=boundary,
                dense_tree_cuts=cuts, best_dense_tree_peak_log2=best_cut['peak_log2_cells'],
                variable_block_scopes={str(i): sorted(scopes[i]) for i in boundary}, domains=domains,
                multiblock_variables=sum(len(scopes[i]) > 2 for i in boundary),
                max_block_log2_cells=max(b['log2_cells'] for b in blocks),
                total_input_table_log2_cells=math.log2(total_input_cells),
                dense_8byte_fits_all_blocks=total_input_cells * 8 <= SPEC['dense_memory_budget_bytes'],
                dense_bitpacked_fits_all_blocks=sum((int(b['cells_exact']) + 7) // 8 for b in blocks) <= SPEC['dense_memory_budget_bytes'],
                nominal_fixed_ticks=healthy, planned_starts_redundant=planned_redundant,
                calendar_log2_history_count_F1=sum(bool(q) for q in data['queues']) * max(0, deadline // delta - 1) if fixed else None,
                common_calendar_markov_dp_cells_upper=2 * (deadline // delta + 1) * (healthy // delta + 1) if fixed and planned_redundant else None)


try:
    inputs = []
    cases = []
    manifest_root = ROOT / 'results/fixed-plan-inputs'
    manifest_bytes = (manifest_root / 'SHA256SUMS.json').read_bytes()
    check('frozen_manifest_hash', hashlib.sha256(manifest_bytes).hexdigest() == SPEC['input_manifest_sha256'])
    manifest = json.loads(manifest_bytes)
    for instance in SPEC['instances']:
        path = manifest_root / instance / 'schedule.json'
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        check('sealed_input_hash:' + instance, sha == manifest[instance + '/schedule.json'])
        data = json.loads(raw)
        ops = data['operations']
        check('identity:' + instance, data['dataset_id'] == instance)
        check('operation_ids', [o['id'] for o in ops] == list(range(len(ops))))
        check('mandatory', not any(o.get('optional', False) for o in ops) and not any(j.get('optional', False) for j in data['jobs']))
        check('unit_grid', all(o[k] % data['delta'] == 0 for o in ops for k in ('work', 'planned_start', 'release')))
        check('alternate_grid', all(a['work'] > 0 and a['work'] % data['delta'] == 0 for o in ops for a in o['alternatives']))
        check('unique_machine_alternatives', all(len({a['machine'] for a in o['alternatives']}) == len(o['alternatives']) for o in ops))
        check('zero_releases', all(o['release'] == 0 for o in ops) and all(j['release'] == 0 for j in data['jobs']))
        check('accepted_quality', all(v is True for v in data.get('quality_results', {}).values()))
        outgoing = [0] * len(ops)
        for o in ops:
            for p in o['predecessors']:
                outgoing[p] += 1
        check('same_job_precedence', all(ops[p]['job'] == o['job'] for o in ops for p in o['predecessors']))
        for job in data['jobs']:
            local = [o for o in ops if o['job'] == job['id']]
            check('complete_chain_to_product_terminal', bool(local)
                  and all(len(o['predecessors']) <= 1 and outgoing[o['id']] <= 1 for o in local)
                  and sum(not o['predecessors'] for o in local) == 1
                  and [o['id'] for o in local if not outgoing[o['id']]] == [job['final_operation']])
        inputs.append(dict(instance=instance, sha256=sha, operations=len(ops), jobs=len(data['jobs']),
                           machines=len(data['queues']), max_technological_outdegree=max(outgoing)))
        for fixed, reduced in ((True, False), (True, True), (False, False)):
            for name in SPEC['partitions']:
                cases.append(census(data, name, fixed, reduced))
    check('registered_cases_complete', len(cases) == 90)
    best = []
    for instance in SPEC['instances']:
        for profile in SPEC['profiles']:
            group = [c for c in cases if c['instance'] == instance and c['profile'] == profile]
            selected = min(group, key=lambda c: (c['max_block_log2_cells'], c['partition']))
            best.append(dict(instance=instance, profile=profile, selected_partition=selected['partition'],
                             boundary_operations=len(selected['boundary_operations']),
                             max_log10_cells=selected['max_block_log2_cells'] * math.log10(2),
                             best_tree_peak_log10=selected['best_dense_tree_peak_log2'] * math.log10(2),
                             multiblock_variables=selected['multiblock_variables'],
                             dense_8byte_fits=selected['dense_8byte_fits_all_blocks'],
                             dense_bitpacked_fits=selected['dense_bitpacked_fits_all_blocks']))
    save('inputs.json', inputs)
    save('sources.json', {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
        'scripts/compositional_feasibility.py', 'docs/COMPOSITIONAL_FEASIBILITY_RU.md',
        'provenance/compositional_feasibility.json')})
    save('cases.json', cases)
    with (OUT / 'summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(best[0]))
        writer.writeheader()
        writer.writerows(best)
    result = dict(status='ANALYSIS_COMPLETE', scientific_verdict='NOT_ESTABLISHED',
                  solver_prototype='NOT_STARTED', completed_profiles=len(cases), expected_profiles=90,
                  checks=CHECKS, input_commit=SPEC['input_commit'], source_commit=os.environ['GITHUB_SHA'],
                  run_id=os.environ['GITHUB_RUN_ID'], census_wall_s=time.perf_counter() - START,
                  mathematical_factorization='EXACT_FOR_FIXED_F1_WITH_FULL_BOUNDARY_TIMES',
                  raw_synthesis='NOMINAL_CONSTRAINT_FACTORIZATION_ONLY_NOT_CHANCE_CERTIFICATION',
                  independent_numerical_risk_validation='NOT_RUN_NO_NEW_RISK_ALGORITHM',
                  best_registered_partitions=best, interpretation=SPEC['interpretation'])
    save('RESULT.json', result)
    save('profile.json', SPEC)
    report = ['# Проверка пучковой композиции и алгебраической склейки', '',
              '**Структурный анализ завершён: 90/90 профилей, десять замороженных задач. Новый решатель и новые виртуальные прогоны не запускались. Сравнительное преимущество остаётся NOT_ESTABLISHED.**', '',
              'Математическая конструкция точной склейки фиксированного исполнения установлена в [протоколе](https://github.com/a-a-k/industrial/blob/' + os.environ['GITHUB_SHA'] + '/docs/COMPOSITIONAL_FEASIBILITY_RU.md). При F1 блок владеет полным календарём своих станков и передаёт точные времена завершений на границах. Уникальность рекурсии DAG исключает повторный счёт одной истории. Общие отказы требуют отдельного общего вероятностного фактора.', '',
              '## Размеры выбранного координатного представления', '',
              'Для каждого профиля показан лучший из ТРЁХ заранее выбранных способов по максимальному размеру плотной локальной таблицы. Это не оптимальное разбиение и не нижняя граница сжатого представления. 10^k обозначает число ячеек максимальной таблицы, а не время расчёта.', '',
              '| Задача | Профиль | Разбиение | Общих операций | Максимальная плотная таблица | Переменных в 3–4 блоках | Все таблицы по 8 байт входят в 4 GiB |',
              '|---|---|---|---:|---:|---:|---|']
    for b in best:
        report.append(f'| {b["instance"]} | {b["profile"]} | {b["selected_partition"]} | {b["boundary_operations"]} | 10^{b["max_log10_cells"]:.1f} | {b["multiblock_variables"]} | {"да" if b["dense_8byte_fits"] else "нет"} |')
    fixed_count = sum(any(c['dense_8byte_fits_all_blocks'] for c in cases if c['instance'] == i and c['profile'] == 'fixed_execution') for i in SPEC['instances'])
    reduced_count = sum(any(c['dense_8byte_fits_all_blocks'] for c in cases if c['instance'] == i and c['profile'] == 'fixed_reduced_execution') for i in SPEC['instances'])
    raw_count = sum(any(c['dense_8byte_fits_all_blocks'] for c in cases if c['instance'] == i and c['profile'] == 'raw_synthesis') for i in SPEC['instances'])
    report += ['', f'Хотя бы одно зарегистрированное разбиение помещает все плотные таблицы в оптимистический бюджет: исходное фиксированное исполнение {fixed_count}/10, после удаления избыточных связей {reduced_count}/10, свободный синтез {raw_count}/10. Даже восемь байт на ячейку не обеспечивают необходимую точность вероятностного сертификата.', '',
               'Дополнительный fixed_reduced_execution удаляет только межблочные технологические связи, уже следующие из другого пути объединённого графа. Полная достижимость проверена до и после удаления. Каждая оставшаяся цепочка последовательно задерживает преемника, поэтому удалённый аргумент максимума не меняет физическую рекурсию ни на одном календаре. Исходные временные окна сохранены. Первый результат 60/60 из запуска44547107348 также сохранён в Releases; версия90/90 добавляет это обычное сокращение перед оценкой размера.', '',
               '## Что установлено математически', '',
               '- Пучковая постановка даёт корректный способ выразить локальные планы и совместимость. Для номинального синтеза это известная CSP-постановка; выбранные назначения, очереди и времена ещё надо найти.',
               '- Округлённые экспоненциальные отказы имеют точное конечное геометрическое представление. При исходных соотношениях средних риск фиксированного плана можно записать полиномом от q=exp(-Δ/(2C0)). Получение коэффициентов не становится бесплатным или полиномиальным.',
               '- В F1 цельная машинная очередь локальна, границы несут времена технологических передач. Для цепочных маршрутов они парные и формально подходят под четыре таблицы K4; много временных координат делает сами таблицы большими.',
               '- Для общей ветви F2 у earliest zero-release плана накопленное общее рабочее время даёт точный простой контроль. F2SI с разными действиями имеет индивидуальные часы и не подменяется этой формулой.',
               '- Для устойчивого синтеза требуется max_plan sum_failures, при одном плане до всех будущих отказов. Подсчёт успешных сочетаний плана и будущего отказа такую оптимизацию не решает.', '',
               '## Что не установлено', '',
               'Нет измеренного выигрыша Signed Network Sums, компактного сжатого представления локальных вероятностных таблиц или аналитически выведенного оптимального устойчивого плана. Перепись не строит W, не считает новый риск и не заменяет сравнительный опыт удобным внутренним показателем.', '',
               'Большая плотная таблица отвергает её непосредственную материализацию в данном бюджете, но не опровергает разреженность, символическое сжатие или другую декомпозицию. Малые/древовидные интерфейсы также доступны обычным junction-tree/BDD/CP-методам. Локальная Markov-DP и common-calendar формула обязательны как сильные прямые контроли.', '',
               '## Решение по следующему этапу', '',
               'Полный новый решатель на основании этой переписи не запускается: источник преимущества с полной ценой ещё не установлен. Следующее необходимое обоснование — компактное вычислимое описание локальных W на этих данных и конкретная операция склейки, которая дешевле сильного обычного контроля после оплаты компиляции и точности. Это продолжение анализа исходной гипотезы, а не ослабление её критерия.', '',
               '## Воспроизводимость', '',
               f'Входы проверены по исходному SHA256SUMS. Проверок: {len(CHECKS)}, отказов 0. Время самой переписи {result["census_wall_s"]:.6f} с; это не время нового метода. Полный runner-снимок включает подготовку и предыдущие попытки в budget.json; текущее задание ещё не завершено в этом снимке.', '',
               'Сводные sizes относятся к успешным состояниям и необходимым earliest/latest окнам; не ко всем сочетаниям календарей. Для фактических завершений сохранён шаг Δ=5, для номинального синтеза использована достаточная gcd-сетка работ: при нулевых releases ранний план любого допустимого порядка лежит на ней. Это не coarsening случайных завершений. Полные домены, переменные границ, три 2|2-разреза обычной свёртки и верхние оболочки Markov-состояний сохранены в cases.json. Критерий общей памяти учитывает сумму четырёх исходных таблиц, отдельно от промежуточных. Никакие новые производственные вероятности не заявляются.', '']
    (OUT / 'REPORT_RU.md').write_text('\n'.join(report))
    print(json.dumps({k: v for k, v in result.items() if k not in ('checks', 'best_registered_partitions')}, ensure_ascii=False))
except Exception as error:
    save('FAILURE.json', dict(status='FAILED', error=str(error), checks=CHECKS,
                              source_commit=os.environ.get('GITHUB_SHA'), run_id=os.environ.get('GITHUB_RUN_ID')))
    raise
