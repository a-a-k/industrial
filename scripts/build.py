"""Build the independent public kernels and unchanged S1 with public adapters."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
out = Path('build'); out.mkdir(exist_ok=True)
flags = ['-std=c++20','-O3','-DNDEBUG','-Wall','-Wextra','-Werror','-Ivendor']
if os.environ.get('S1_ONLY')!='1':
    subprocess.run(['g++',*flags,'engines/main.cpp','engines/tsfg_op/grid.cpp',
        'engines/des_ref/des.cpp','engines/dag_ref/dag.cpp','-o',str(out/'simulator')],check=True)
    (out/'environment.json').write_text(json.dumps(dict(
        compiler=subprocess.check_output(['g++','--version'],text=True),flags=flags,
        simulator_sha256=hashlib.sha256((out/'simulator').read_bytes()).hexdigest(),
        run_id=os.environ['GITHUB_RUN_ID'],commit=os.environ['GITHUB_SHA'],
        cpuinfo=Path('/proc/cpuinfo').read_text()),indent=2))
if os.environ.get('PUBLIC_ONLY')=='1':raise SystemExit(0)
source = Path('.private/upstream'); engine=source/'engine'
expected='8510baf28673758f1e437d2dbc5a51ead9843a3b'
actual=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
if actual != expected: raise SystemExit('Wrong S1 source version')
if os.environ.get('TSFG_TEST_EVIDENCE'):
    summary=json.loads(Path(os.environ['TSFG_TEST_EVIDENCE']).read_bytes())
    if summary['source_commit']!=expected or summary['go_version']!=subprocess.check_output(['go','version'],text=True).strip():
        raise SystemExit('Upstream test evidence version mismatch')
    passed=summary['tests_passed']
    summary=dict(summary,reused_test_evidence=True)
else:
    test=subprocess.run(['go','test','-json','./...'],cwd=engine,capture_output=True,text=True,timeout=1200)
    events=[json.loads(s) for s in test.stdout.splitlines() if s.startswith('{')]
    passed=sum(e.get('Action')=='pass' and bool(e.get('Test')) for e in events)
    summary=dict(source_commit=expected,upstream_test_exit=test.returncode,tests_passed=passed,
                 source_modified=False,public_source=False,public_binary=False)
if summary['upstream_test_exit'] or passed < 157:
    (out/'tsfg-provenance.json').write_text(json.dumps(summary,indent=2))
    raise SystemExit('S1 upstream tests failed; private diagnostics omitted')
for name in ('operation_adapter.go','extended_adapter.go','pbr_adapter.go','audit_adapter.go','aggregate_adapter.go'):
    shutil.copyfile(Path('engines/tsfg_op')/name,engine/'cmd/ozon-engine'/name)
binary=Path('.private/runtime/tsfg').resolve(); binary.parent.mkdir(parents=True,exist_ok=True)
build=subprocess.run(['go','build','-trimpath','-o',str(binary),'./cmd/ozon-engine'],cwd=engine,capture_output=True,text=True,timeout=300)
if build.returncode: raise SystemExit('S1 adapter build failed; private diagnostics omitted')
summary.update(go_version=subprocess.check_output(['go','version'],text=True).strip(),
    binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
    adapter_sha256=hashlib.sha256(Path('engines/tsfg_op/operation_adapter.go').read_bytes()).hexdigest())
(out/'tsfg-provenance.json').write_text(json.dumps(summary,indent=2)+'\n')
print('Independent DES/DAG and original S1 adapter built; upstream tests:',passed)
