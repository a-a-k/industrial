"""Reconcile frozen campaign evidence; no simulations or project dependencies."""
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Actions only')

ROOT = Path.cwd()
OUT = ROOT / 'output/campaign-audit'
OUT.mkdir(parents=True, exist_ok=True)
spec = json.loads((ROOT / 'provenance/campaign_audit.json').read_text())
checks = []


def read(path):
    return json.loads((ROOT / path).read_text())


def rows(path):
    with (ROOT / path).open(newline='') as stream:
        return list(csv.DictReader(stream))


def check(name, actual, expected):
    checks.append(dict(name=name, actual=actual, expected=expected, passed=actual == expected))


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


original = read('results/industrial/RESULT.json')
check('original_blocks', original['blocks'], {**{f'E{i}': 'PASS' for i in range(1, 6)}, 'E6': 'PARTIAL'})
check('original_DES_DAG_trajectories', [original['counters'][k] for k in ('des_completed', 'dag_completed')], [30720, 30720])
check('original_S1_trajectories', original['counters']['tsfg_completed'], 2560)
check('original_engine_mismatches', original['counters']['engine_mismatches'], 0)
check('original_completed_cost_cases', original['cost_cases_complete'], 39)
check('original_timeouts', original['counters']['measurement_timeouts'], 24)
extension = read('results/timeout-extension/RESULT.json')
check('extension_outputs', extension['cost_cases_with_full_outputs_after_extension'], 41)
check('extension_complete', extension['status'], 'COMPLETE')
check('extension_preserves_limits', extension['times_from_different_limits_pooled'], False)

e2e = read('results/end-to-end/PRIMARY_RESULT.json')
check('end_to_end_completed_processes', e2e['observed_complete_processes'], 648)
runner_pairs = [r for c in e2e['comparisons'] for r in c['runners']]
check('end_to_end_runner_pairs', len(runner_pairs), 36)
check('end_to_end_S1_slower', sum(r['rows']['s1_simpat']['median_s'] > r['rows']['dag_direct']['median_s'] for r in runner_pairs), 36)
check('end_to_end_first_use_S1_slower', sum(r['rows']['s1_simpat']['first_use_total_s'] > r['rows']['dag_direct']['first_use_total_s'] for r in runner_pairs), 36)

local = read('results/fixed-plan-reinforcement/VERDICT.json')
check('local_contrasts_include_zero', local['contrasts_including_zero'], 100)
check('local_advantages', local['confirmed_pairwise_external_advantages'], 0)
local_rows = rows('results/fixed-plan-reinforcement/summary.csv')
check('local_conditions', len(local_rows), 20)
check('local_noop', sum(r['edit'] == 'none' for r in local_rows), 7)

inverse = read('results/inverse-conditions/RESULT.json')
check('inverse_configurations', inverse['completed_configurations'], 288)
check('inverse_cases', inverse['completed_cases'], 20)
check('inverse_cases_with_feasible', sum(r['certified_feasible'] > 0 for r in inverse['summaries']), 20)
check('inverse_minimum_proved_cases', sum(r['frontier_minimum_proved'] > 0 for r in inverse['summaries']), 16)
frontier = rows('results/inverse-conditions/frontier.csv')
check('inverse_frontier_changed_plans', sum(int(r['reassigned_operations']) > 0 or int(r['queue_inversions']) > 0 for r in frontier), 0)

addressed = read('results/addressed-repair/RESULT.json')
conditions = rows('results/addressed-repair/conditions.csv')
decisions = rows('results/addressed-repair/decisions.csv')
recommendations = rows('results/addressed-repair/recommendations.csv')
check('addressed_configs_in_csv', len(conditions), 86)
check('addressed_decisions_in_csv', len(decisions), 300)
check('addressed_cases_in_csv', len(recommendations), 20)
check('addressed_external_samples', sum(int(r['samples']) for r in conditions), 704512)
check('addressed_baseline_status', addressed['baseline_status_counts'], dict(FEASIBLE=4, INFEASIBLE=16, UNRESOLVED=0))
grouped = {}
for row in decisions:
    grouped.setdefault((row['case'], row['repeat']), []).append(row)
check('addressed_comparison_triplets', len(grouped), 100)
check('addressed_equal_cardinalities', sum(len(v) == 3 and {r['method'] for r in v} == {'lazy', 'scan', 'cheap'} and len({int(r['k']) for r in v}) == 1 for v in grouped.values()), 100)
check('addressed_confirmed_wins', addressed['winning_cases'], [])
sparse = [r for r in recommendations if r['baseline_status'] == 'INFEASIBLE' and r['status'] == 'FEASIBLE' and 0 < int(r['machine_count']) < int(r['used_machines'])]
check('addressed_insufficient_with_sparse', len(sparse), 15)
example = next(r for r in recommendations if r['case'] == 'Mk01-F1')
check('example_successes', int(example['successes']), 7938)
check('example_origin', example['origin_methods'], 'slack')
check('example_machines', example['machines'], '0;1;2')

# Check only files actually mirrored in Git. A missing raw entry is not silently
# declared verified: manifests can describe a larger Release than this checkout.
manifest_rows = []
for manifest in sorted((ROOT / 'results').glob('*/SHA256SUMS.json')):
    for relative, expected in json.loads(manifest.read_text()).items():
        target = (manifest.parent / relative).resolve()
        if not target.is_relative_to(manifest.parent.resolve()):
            raise ValueError('Manifest escapes evidence root')
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
        manifest_rows.append(dict(manifest=str(manifest.relative_to(ROOT)), file=relative,
                                  expected=expected, actual=actual,
                                  status='not_mirrored' if actual is None else 'match' if actual == expected else 'mismatch'))
check('mirrored_manifest_hash_mismatches', sum(r['status'] == 'mismatch' for r in manifest_rows), 0)

sources = sorted({s for item in spec['phases'] + spec['findings'] for s in item['sources']} | {
    'results/timeout-extension/RESULT.json',
    'results/end-to-end/PRIMARY_RESULT.json',
    'results/fixed-plan-reinforcement/summary.csv',
    'results/inverse-conditions/frontier.csv',
    'results/addressed-repair/RESULT.json',
})
inventory = []
for path in sources:
    target = ROOT / path
    check('source_exists:' + path, target.is_file(), True)
    if target.is_file():
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        frozen = subprocess.run(['git', 'show', spec['evidence_commit'] + ':' + path],
                                check=True, capture_output=True).stdout
        check('source_unchanged_since_evidence_commit:' + path,
              actual, hashlib.sha256(frozen).hexdigest())
        inventory.append(dict(path=path, sha256=actual))

run_states = []
for run_id in spec['runs']:
    request = urllib.request.Request(
        f'https://api.github.com/repos/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{run_id}',
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                state = json.load(response)
            break
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
    run_states.append({k: state[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'html_url', 'run_attempt', 'created_at', 'updated_at')})
    check('run_complete:' + str(run_id), state['status'], 'completed')
    check('run_conclusion:' + str(run_id), state['conclusion'],
          'failure' if run_id in spec['expected_failed_runs'] else 'success')

budget = read('output/budget.json')
integrity = {k: sum(r['status'] == k for r in manifest_rows) for k in ('match', 'mismatch', 'not_mirrored')}
result = dict(status='COMPLETE' if all(r['passed'] for r in checks) else 'CHECK_FAILED',
              evidence_commit=spec['evidence_commit'], audit_source=os.environ['GITHUB_SHA'],
              run_id=os.environ['GITHUB_RUN_ID'], generated_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
              scope=spec['scope'], method=spec['method'], checks=checks, integrity=integrity,
              scientific_advantage='NOT_ESTABLISHED', current_audit_job_excluded_from_completed_budget=True,
              completed_runner_seconds_at_audit_start=budget['completed_s'],
              reserved_runner_seconds_at_audit_start=budget['reserved_s'],
              runner_limit_seconds=budget['limit_s'])
save('RESULT.json', result)
save('source_inventory.json', inventory)
save('manifest_checks.json', manifest_rows)
save('workflow_runs.json', run_states)
save('budget_at_audit_start.json', budget)
save('audit_specification.json', spec)

def links(paths):
    return ', '.join(f'[{p}](https://github.com/{os.environ["GITHUB_REPOSITORY"]}/blob/{spec["evidence_commit"]}/{p})' for p in paths)

report = [
    '# Аудит: что планировалось и что выполнено', '',
    spec['summary'], '',
    f'Срез доказательств: `{spec["evidence_commit"]}`. Статус сверки: **{result["status"]}**. Новые эксперименты не запускались.', '',
    spec['scope'], '',
    '## Сопоставление целей и результатов', '',
    '| Этап | Собирались | Сделали | Допустимый вывод |',
    '|---|---|---|---|'
]
for phase in spec['phases']:
    report.append('| ' + ' | '.join(phase[k] for k in ('id', 'intended', 'actual', 'conclusion')) + ' |')
report += ['', '## Проверяемые источники по этапам', '']
for phase in spec['phases']:
    report += [f'**{phase["id"]}:** ' + links(phase['sources']), '']
report += ['## Существенные замечания', '']
for finding in spec['findings']:
    report += [f'### {finding["id"]}. {finding["title"]}', '',
               f'Статус: {finding["status"]}. {finding["detail"]}', '', links(finding['sources']), '']
report += ['## Конкретный положительный результат и его происхождение', '',
           f'Mk01/F1: исходный план выполнил срок в 7373/8192 испытаний (90,00%). Ускорение ремонта станков {example["machines"]} из шести дало {example["successes"]}/{example["samples"]} (96,90%); одновременная нижняя граница 96,19% превышает цель 95%. Изменён средний экспоненциальной длительности ремонта до округления до 25% исходного, план и срок сохранены.', '',
           'Этот практический набор происходит из простого правила slack; он не является победой D. В Mk06/F2SI достаточная практическая рекомендация происходит из load, тогда как шестистаночный ответ D остаётся неопределённым. Достаточность конкретного решения и преимущество метода его поиска — разные утверждения.', '',
           '## Что осталось открытым', '']
report += ['- ' + item for item in spec['remaining']]
report += ['', '## Проверка исполнения, целостности и бюджета', '', spec['method'], '',
           f'Проверок сводок и источников: {len(checks)}; не прошли: {sum(not c["passed"] for c in checks)}. Хеши имеющихся файлов: {integrity["match"]} совпадений, {integrity["mismatch"]} расхождений. Записей манифестов вне локальной Git-копии: {integrity["not_mirrored"]}. Они относятся к более полным выпускам; их содержимое этим аудитом повторно не скачивалось и не проверялось.', '',
           'Первичные источники сохранены в Releases; данный аудит не повторяет все симуляции, не проверяет заново каждый сырой архив и не является новой независимой валидацией предприятия. Инвентарь хешей фиксирует, какие отчёты действительно прочитаны машинной сверкой.', '',
           f'Снимок на начало аудита: завершённые задания {budget["completed_s"]:.0f} с ({budget["completed_s"] / 3600:.3f} runner-часа); резерв незавершённых {budget["reserved_s"]:.0f} с; предел {budget["limit_s"] / 3600:.0f} runner-часа. Учтены подготовка, ошибки, прежние попытки и отчёты. Сам текущий аудит ещё не завершён в этом снимке; это не закрытый окончательный счёт кампании.', '',
           'Проверены состояния ключевых Actions, включая сохранённую неудачную квалификацию адресного ремонта. Её дефект сравнения неиспользуемых скрытых календарей исправлен до принятой квалификации; неудачный запуск не входит в основную проверочную выборку. Служебные сбои и повторы зафиксированы в прежних run registries; они не означают срывы производственного срока.', '',
           'Первая попытка данного аудита 44089890239 завершилась до сверки источников: Git в контейнере отверг каталог по safe.directory. Настройка исправлена; бюджет и выпуск неудачной попытки сохранены. Экспериментальные результаты этим сбоем не затронуты.', '',
           '## Решение по результатам аудита', '',
           'Сохранять исходные положительные результаты корректности и конкретные достаточные условия ремонта. Не заявлять подтверждённое превосходство поиска, почти стопроцентную точность прогноза, глобальную оптимальность или доказанную лёгкость всей системы. Следующий сравнительный опыт имеет смысл только с заранее выбранным одним из оставшихся критериев; этот аудит новых опытов не запускает.', '']
(OUT / 'REPORT_RU.md').write_text('\n'.join(report))
print(json.dumps({k: v for k, v in result.items() if k != 'checks'}, ensure_ascii=False))
if result['status'] != 'COMPLETE':
    raise SystemExit('Audit evidence checks failed; inspect RESULT.json')
