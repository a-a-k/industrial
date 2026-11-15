"""Check the measurement window of subprocess RSS without running algorithms."""
import gc
import json
import os
from pathlib import Path
import resource
import sys
from .common import actions_only,execute,write_json


def memory():
    values={}
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith(('VmRSS:','VmHWM:')):
            key,value=line.split(':',1);values[key]=int(value.split()[0])*1024
    return dict(values,ru_maxrss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)


def run():
    root=Path('output/resource-window');root.mkdir(parents=True,exist_ok=True)
    child='import json;from industrial.resource_diagnostics import memory;print(json.dumps(memory()))'
    observations=[]
    for size in (0,64*1024**2):
        if size:
            payload=bytearray(size)
            for offset in range(0,size,4096):payload[offset]=1
            parent_peak=memory();del payload;gc.collect()
        else:parent_peak=memory()
        parent_after_free=memory()
        process=execute([sys.executable,'-c',child],timeout=1200)
        if process['status']!='OK':raise ValueError('RSS control child failed')
        observation=dict(parent_allocation_bytes=size,parent_with_allocation=parent_peak,
            parent_after_free=parent_after_free,child=json.loads(process['stdout']),process=process)
        observations.append(observation)
    before,after=observations
    gap=after['child']['ru_maxrss']-after['child']['VmHWM']
    detected=gap>32*1024**2 and after['child']['ru_maxrss']>before['child']['ru_maxrss']+32*1024**2
    result=dict(status='COMPLETE',python=sys.version,observations=observations,
        parent_current_rss_after_free=after['parent_after_free']['VmRSS'],
        pre_exec_history_in_rusage_rss_detected=detected,
        algorithm_runs=0,raw_experimental_measurements_modified=False,
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'])
    write_json(root/'RESULT.json',result)
    lines=['# Окно учёта RSS в повторных измерениях','',
        'Короткий контроль выполнен в том же образе Python 3.11, с одним CPU, 4 GiB '
        'и тем же common.execute/subprocess, без запуска исследуемых алгоритмов.',
        '', '| Выделено родителем, MiB | RSS родителя после освобождения, MiB | ru_maxrss ребёнка, MiB | VmHWM ребёнка после exec, MiB |',
        '|---:|---:|---:|---:|']
    for row in observations:
        lines.append(f"| {row['parent_allocation_bytes']/1024**2:.2f} | {row['parent_after_free']['VmRSS']/1024**2:.2f} | "
            f"{row['child']['ru_maxrss']/1024**2:.2f} | {row['child']['VmHWM']/1024**2:.2f} |")
    if detected:
        lines+=['', 'Контроль подтвердил: ru_maxrss дочернего процесса включает историю запуска до exec. '
            'Предварительная проверка большого входного файла в родителе может задавать этот пик даже после освобождения памяти.',
            'Поэтому RSS в дополнении о тайм-аутах сохраняется как наблюдённый пик жизненного цикла процесса. '
            'Его нельзя интерпретировать как изолированный пик памяти вычислительного метода. '
            'Чистый пик метода по этим данным не восстановлен; вычитание пика родителя некорректно. '
            'Сырые значения и времена не изменяются.']
    else:
        lines+=['', 'Этот контроль не подтвердил предполагаемое влияние истории запуска на ru_maxrss. '
            'Сырые значения сохраняются без вычитаний или исправлений.']
    lines+=['', '[Определение getrusage](https://man7.org/linux/man-pages/man2/getrusage.2.html): '
        'ресурсные счётчики сохраняются через execve. Контроль и сырые наблюдения приведены в RESULT.json.']
    (root/'RESOURCE_NOTE_RU.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':actions_only();run()
