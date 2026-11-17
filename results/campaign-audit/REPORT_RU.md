# Аудит: что планировалось и что выполнено

Основная экспериментальная работа выполнена. Краш-тесты выявляют модельный риск, а проверенные вмешательства дают достаточные условия ремонта. Преимущество S1/SIMPAT и предложенного поиска над сильными открытыми контролями не установлено; легковесность полного продукта пока не измерена.

Срез доказательств: `15d0c12010acd42f46e9ae51e29b25f540bb41c3`. Статус сверки: **COMPLETE**. Новые эксперименты не запускались.

Исходный E1–E6 и последующие расширения в a-a-k/industrial. Архивные отчёты сохраняют свои исходные статусы. Старый Industrial plan и чужие профили DES не объединяются с этой серией.

## Сопоставление целей и результатов

| Этап | Собирались | Сделали | Допустимый вывод |
|---|---|---|---|
| E1–E5 | Проверить производственный смысл координат, идентификацию, точные границы, сокращения и перенос на Mk01–Mk10. | E1–E5 PASS; 30 720 независимых сценариев DES/DAG, 2 560 проверок исходным S1, ноль расхождений. Полные свидетели, размерности за прежними пределами и внешние исходы проверены. | Исходные проверки выполнены. Они не требуют победы по скорости и не устанавливают точность прогноза реального предприятия. |
| E6 и повтор тайм-аутов | Сопоставимо измерить время, память, представление и завершённость; сохранить остановки. | Исходно 39/41 полностью завершённых случаев и 24 тайм-аута при 300 с. Дополнение завершило оба оставшихся случая при 1200 с: ответы доступны для 41/41. Чистый пик памяти методов по прежнему RSS не восстановлен. | Исходный статус PARTIAL сохраняется; дополнение COMPLETE. Разные лимиты и runners нельзя смешивать. Обязанность чистого сравнения памяти остаётся незакрытой. |
| Генерация и выбор цели плана | Генерировать план из вводных по выбираемой цели; проверить дополнительную пользу учёта риска. | Реализованы номинальная длительность, вероятность срока F1, худший режим и Парето; основные проверки генератора — Mk01/Mk05/Mk10, три seed. Добавлен сильный CP-SAT и короткий CP-контроль. Дополнительный поиск подтверждённого преимущества не дал. | Работает поиск лучшего найденного плана в ограниченном бюджете. Глобальный оптимум не доказан. Улучшение стандартным CP нельзя приписывать краш-тестам. |
| Полная стоимость краш-теста | Получить тот же полезный результат дешевле либо лучший при сопоставимой полной цене, учитывая генерацию воздействий и подготовку. | 648/648 процессов, 36 пар условие/runner. S1/SIMPAT дороже indexed DAG/direct MC во всех 36 парах, также с подготовкой. DES независимо проверял исходы, но не был измеряемым участником этой таблицы. | Преимущество полного S1/SIMPAT для проверенного класса не установлено. Это не прямое сравнение времени S1 с обычным DES и не отрицательный результат для всех моделей TSFG. |
| Фиксированный план и локальная правка | Краш-тест утверждённого плана → слабые места → осуществимая правка → независимое улучшение выпуска. | Все десять фиксированных CP-планов, 20 условий F1/F2: 13 правок и 7 решений оставить план. Ноль подтверждённых улучшений; все 100 сравнительных интервалов включают ноль. | Диагностика задержек выполнена. Польза выбранных диагностической стратегией локальных правок не подтверждена. Это не проверка отсутствия любой полезной правки во всём каталоге. Сумма ожиданий сама по себе не доказывает причинность. |
| План и ремонт для цели 95% | Найти минимальное усиление; разрешено менять и план, и параметры ремонта. | 288/288 сочетаний; достаточные условия найдены для 20/20. Все подтверждённые недоминируемые варианты сохраняют план и меняют равномерный ремонт. Минимальность в конечном меню подтверждена в 16 случаях, в четырёх неопределённа. | Получены проверенные достаточные условия. Аналитические рабочие окна — ограничения, а выбор конкретного усиления выполнен численно. Глобальный аналитический оптимум не получен. |
| Адресный ремонт | Вместо ускорения ремонта всюду найти конкретные станки и проверить пользу поиска против прямого перебора и дешёвой комбинации правил. | 20/20 условий, 86/86 наборов, по 8192 новых исхода. Четыре исходных случая достаточны; для 15 из 16 недостаточных найдены сертифицированные наборы на части оборудования. Во всех 100 тройках D/B/C одинаковое выбранное число станков; сравнительных побед ноль. | Конкретные модельные рекомендации получены, преимущество нового поиска не установлено. F2SI — явно дополнительная модель вмешательства, а не автоматически доказанное поведение общих отказов F2. |
| Легковесный подход | Оформить компактный путь план → риск → слабое место → проверенная рекомендация с меньшей общей трудоёмкостью. | Есть работающий исследовательский стенд и конкретные рекомендации; простые правила дают сопоставимые ответы. Время моделирования предприятия, интеграция, сопровождение и полный продуктовый цикл не измерялись. | Это направление развития, а не доказанное преимущество системы целиком. Старые отрицательные сравнения сохраняют силу. |

## Проверяемые источники по этапам

**E1–E5:** [docs/PROTOCOL.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/PROTOCOL.md), [results/industrial/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/industrial/REPORT_RU.md), [results/industrial/RESULT.json](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/industrial/RESULT.json)

**E6 и повтор тайм-аутов:** [results/timeout-extension/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/timeout-extension/REPORT_RU.md), [results/timeout-extension/RESULT.json](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/timeout-extension/RESULT.json), [results/timeout-extension/RESOURCE_NOTE_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/timeout-extension/RESOURCE_NOTE_RU.md)

**Генерация и выбор цели плана:** [docs/PLAN_GENERATION.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/PLAN_GENERATION.md), [results/objectives/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/objectives/REPORT_RU.md), [results/planner-comparison/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/planner-comparison/REPORT_RU.md), [results/cp-prefix/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/cp-prefix/REPORT_RU.md), [results/decision-options/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/decision-options/REPORT_RU.md)

**Полная стоимость краш-теста:** [docs/END_TO_END_CRITERION_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/END_TO_END_CRITERION_RU.md), [results/end-to-end/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/end-to-end/REPORT_RU.md), [results/end-to-end/PRIMARY_RESULT.json](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/end-to-end/PRIMARY_RESULT.json)

**Фиксированный план и локальная правка:** [docs/FIXED_PLAN_DIAGNOSTICS_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/FIXED_PLAN_DIAGNOSTICS_RU.md), [docs/FIXED_PLAN_REINFORCEMENT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/FIXED_PLAN_REINFORCEMENT_RU.md), [results/fixed-plan-reinforcement/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/fixed-plan-reinforcement/REPORT_RU.md), [results/fixed-plan-reinforcement/VERDICT.json](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/fixed-plan-reinforcement/VERDICT.json)

**План и ремонт для цели 95%:** [docs/INVERSE_CONDITIONS_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/INVERSE_CONDITIONS_RU.md), [results/inverse-conditions/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/inverse-conditions/REPORT_RU.md), [results/inverse-conditions/RESULT.json](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/inverse-conditions/RESULT.json)

**Адресный ремонт:** [docs/ADDRESSED_REPAIR_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/ADDRESSED_REPAIR_RU.md), [results/addressed-repair/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/addressed-repair/REPORT_RU.md), [results/addressed-repair/conditions.csv](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/addressed-repair/conditions.csv), [results/addressed-repair/decisions.csv](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/addressed-repair/decisions.csv), [results/addressed-repair/recommendations.csv](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/addressed-repair/recommendations.csv)

**Легковесный подход:** [README.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/README.md), [results/addressed-repair/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/addressed-repair/REPORT_RU.md), [results/end-to-end/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/end-to-end/REPORT_RU.md)

## Существенные замечания

### A01. Смешивались разные цели и критерии успеха

Статус: ограничение вывода. Исходный E1–E6 проверяет перенос, корректность и затраты; положительное ускорение не было условием. Позднее появились самостоятельные гипотезы оптимизации и ремонта. Их отрицательные результаты не отменяют исходные PASS. Техническое COMPLETE не означает подтверждённого сравнительного вклада.

[docs/PROTOCOL.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/PROTOCOL.md), [docs/RESULT_SCOPE_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/RESULT_SCOPE_RU.md)

### A02. Риск выполнения срока не равен точности прогноза

Статус: не доказано. 95% — требуемая вероятность вовремя выпустить всю партию в заданном законе поломок. Совпадение движков проверяет реализацию. Ошибки 2,43/1,75 п.п. относятся к независимым выборкам одной синтетической модели; при полных наблюдениях оценка совпадает с частотой. Ни одно из этих чисел не является почти стопроцентной точностью предсказания реального предприятия.

[results/industrial/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/industrial/REPORT_RU.md), [docs/RESULT_SCOPE_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/RESULT_SCOPE_RU.md)

### A03. Рост качества CP-плана нельзя приписывать риск-информации

Статус: не доказано. CP-SAT оптимизировал номинальное расписание. В архивном выборе из одного пула nominal и MC совпали в 8/9 случаев; единственное отличие выиграло один рабочий исход. Это не подтверждение внешнего преимущества краш-тестов как правила выбора.

[results/cpsat/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/cpsat/REPORT_RU.md), [results/decision-options/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/decision-options/REPORT_RU.md), [results/cp-prefix/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/cp-prefix/REPORT_RU.md)

### A04. 146 байт и почти равное время относились к проекции после полной модели

Статус: уточнено; дефекты исправлены ранее. Проекция сначала читала журнал и строила полную модель. Поэтому 221,37 и 220,51 с не измеряют прямое сокращённое построение. В отдельной корректной паре full/direct получены 240,78 и 107,74 с. Файл 146 байт хранит только R, а не все запросы полной модели. Аудит реализации также исправил обработку записей вне окна и неверных времён; архивные входы отдельно перепроверены.

[results/implementation-audit/AUDIT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/implementation-audit/AUDIT_RU.md), [results/implementation-audit/RESULT.json](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/implementation-audit/RESULT.json)

### A05. Полное сравнение по времени проведено с DAG, не с DES

Статус: не выполнено в этом профиле. Независимый DES проверяет правильность; сильный быстрый конкурент в измерениях — indexed DAG/direct MC. Прямая таблица полной скорости S1 против обычного DES в industrial end-to-end отсутствует. Старые сравнения из другого репозитория нельзя переносить на этот профиль.

[docs/END_TO_END_CRITERION_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/END_TO_END_CRITERION_RU.md), [results/end-to-end/REPORT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/end-to-end/REPORT_RU.md)

### A06. Аналитика не вывела глобально оптимальное усиление

Статус: граница применимости. Необходимые окна и достаточное условие доступного времени ограничивают решения. Адресные наборы выбираются по 512 рабочим сценариям и проверяются на 8192 новых. Минимум по рабочему банку или среди сертифицированных наборов не равен минимуму истинной вероятности и не доказывает уникальную причину срыва.

[docs/INVERSE_CONDITIONS_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/INVERSE_CONDITIONS_RU.md), [docs/ADDRESSED_REPAIR_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/ADDRESSED_REPAIR_RU.md), [results/addressed-repair/recommendations.csv](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/addressed-repair/recommendations.csv)

### A07. Адресный F2SI отделён от исходного F2

Статус: явная новая предпосылка. Общие случайные инновации и индивидуальные часы восстановления задают реакцию на адресный ремонт. Равномерные действия восстанавливают прежний F2, но это не идентифицирует реакцию реальных общих отказов. Сравнивать адресные рекомендации как проверку неизменённого F2 некорректно.

[docs/ADDRESSED_REPAIR_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/ADDRESSED_REPAIR_RU.md), [provenance/addressed_repair.json](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/provenance/addressed_repair.json)

### A08. Чистый расход памяти и полная продуктовая трудоёмкость неизвестны

Статус: незакрытое измерение. RSS прежней серии включает историю родительского процесса до exec; вычитанием её не исправить. Поздние first-use стоимости составлены из измеренных фаз, а не из пяти независимых внедрений продукта. Реальная стоимость ускорения ремонта, лицензии конкурентов и предприятие не испытывались.

[results/timeout-extension/RESOURCE_NOTE_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/timeout-extension/RESOURCE_NOTE_RU.md), [industrial/addressed_report.py](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/industrial/addressed_report.py), [results/fixed-plan-reinforcement/COMPARISON_CLASSES_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/results/fixed-plan-reinforcement/COMPARISON_CLASSES_RU.md)

### A09. Поздние протоколы содержат следы предыдущих редакций

Статус: не влияет на численные итоги. В addressed-протоколе основной текст сохраняет раннее изложение D/B, тогда как вводная часть и код включают обязательный третий контроль C. В fixed-local рядом с уточнением о sunk initial CP остаётся более общая старая формулировка стоимости. Реальные итоговые проверки включают контроли и стоимость; численного пропуска здесь не найдено. Замороженные документы не переписываются этим аудитом.

[docs/ADDRESSED_REPAIR_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/ADDRESSED_REPAIR_RU.md), [docs/FIXED_PLAN_REINFORCEMENT_RU.md](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/docs/FIXED_PLAN_REINFORCEMENT_RU.md), [industrial/addressed_report.py](https://github.com/a-a-k/industrial/blob/15d0c12010acd42f46e9ae51e29b25f540bb41c3/industrial/addressed_report.py)

## Конкретный положительный результат и его происхождение

Mk01/F1: исходный план выполнил срок в 7373/8192 испытаний (90,00%). Ускорение ремонта станков 0;1;2 из шести дало 7938/8192 (96,90%); одновременная нижняя граница 96,19% превышает цель 95%. Изменён средний экспоненциальной длительности ремонта до округления до 25% исходного, план и срок сохранены.

Этот практический набор происходит из простого правила slack; он не является победой D. В Mk06/F2SI достаточная практическая рекомендация происходит из load, тогда как шестистаночный ответ D остаётся неопределённым. Достаточность конкретного решения и преимущество метода его поиска — разные утверждения.

## Что осталось открытым

- Исходный E6: чистое сопоставимое измерение памяти остаётся открытым; первичные тайм-ауты не стираются дополнением.
- Просьба сравнить с DES: в данном полном профиле нет отдельного измеряемого DES-участника. Корректность DES и сильный DAG-контроль эту конкретную таблицу не заменяют.
- Заявление о лёгкости всей системы: нет одинаково учтённой подготовки модели, интеграции и полного прикладного цикла по сравнению с прямым DES/DAG и теми же дешёвыми правилами.
- Реальное производство: нет внешней заводской проверки законов отказов, качества прогноза, достижимости и цены ремонта. Это граница заявлений, не скрытое выполненное испытание.
- Глобально оптимальные условия и преимущество нового поиска не доказаны. Отрицательная завершённая серия не становится невыполненным запуском и не требует бесконечных повторов.
- E7 с дублированием оборудования из исходного предложения не выполнен в этой форме. Он был дополнительным; его нельзя объявлять обязательным провалом E1–E6 или считать заменённым опытом ремонта.

## Проверка исполнения, целостности и бюджета

Сверка протоколов, опубликованных JSON/CSV и отчётов; пересчёт сводных счётчиков из сохранённых таблиц, проверка хешей имеющихся файлов, состояний ключевых Actions и полного снимка runner-бюджета. Новые симуляции и повтор всей квалификации не выполняются. Независимая проверка интерпретации не обнаружила новых существенных численных ошибок; это не доказательство отсутствия всех дефектов кода.

Проверок сводок и источников: 137; не прошли: 0. Хеши имеющихся файлов: 925 совпадений, 0 расхождений. Записей манифестов вне локальной Git-копии: 0. Они относятся к более полным выпускам; их содержимое этим аудитом повторно не скачивалось и не проверялось.

Первичные источники сохранены в Releases; данный аудит не повторяет все симуляции, не проверяет заново каждый сырой архив и не является новой независимой валидацией предприятия. Инвентарь хешей фиксирует, какие отчёты действительно прочитаны машинной сверкой.

Снимок на начало аудита: завершённые задания 109155 с (30.321 runner-часа); резерв незавершённых 5400 с; предел 72 runner-часа. Учтены подготовка, ошибки, прежние попытки и отчёты. Сам текущий аудит ещё не завершён в этом снимке; это не закрытый окончательный счёт кампании.

Проверены состояния ключевых Actions, включая сохранённую неудачную квалификацию адресного ремонта. Её дефект сравнения неиспользуемых скрытых календарей исправлен до принятой квалификации; неудачный запуск не входит в основную проверочную выборку. Служебные сбои и повторы зафиксированы в прежних run registries; они не означают срывы производственного срока.

Первая попытка данного аудита 44089890239 завершилась до сверки источников: Git в контейнере отверг каталог по safe.directory. Настройка исправлена; бюджет и выпуск неудачной попытки сохранены. Экспериментальные результаты этим сбоем не затронуты.

## Решение по результатам аудита

Сохранять исходные положительные результаты корректности и конкретные достаточные условия ремонта. Не заявлять подтверждённое превосходство поиска, почти стопроцентную точность прогноза, глобальную оптимальность или доказанную лёгкость всей системы. Следующий сравнительный опыт имеет смысл только с заранее выбранным одним из оставшихся критериев; этот аудит новых опытов не запускает.
