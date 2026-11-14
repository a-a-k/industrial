"""Complete E1–E4 qualification on GitHub-hosted Actions."""
from pathlib import Path
import hashlib
import json
import os
import unittest
from .common import actions_only,read_json,write_json


def run():
    actions_only()
    root=Path('output/qualification');root.mkdir(parents=True,exist_ok=True)
    manifest=read_json('provenance/sources.json')
    for row in manifest['files']:
        if hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Frozen source checksum mismatch: '+row['path'])
    suite=unittest.defaultTestLoader.discover('tests')
    with (root/'tests.txt').open('w') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    report=dict(status='CORE_PASS' if result.wasSuccessful() and not result.skipped else 'FAIL',
        tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
        protocol='industrial-e1-e6-v1',family='cartesian_known_coordinate_fibers',
        acceptance_pending=['maximum_industrial_schema','E4_production_masks_and_refinement','isolated_identification_job'],
        implementation={str(p):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path('industrial')/n for n in ('binding.py','model.py','solver.py','targets.py','oracle.py','statistics.py','production.py','inputs.py')]})
    write_json(root/'qualification.json',report)
    print((root/'tests.txt').read_text())
    print(json.dumps(report))
    if report['status']!='CORE_PASS':raise SystemExit('Core qualification failed')


if __name__=='__main__':run()
