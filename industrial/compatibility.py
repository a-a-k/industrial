"""Narrow, qualified replacement of certificate construction only."""
from pathlib import Path
from .common import read_json,digest
from .releases import fetch


def verify_implementation(expected):
    current={name:digest(Path(name).read_bytes()) for name in expected}
    changed=[name for name in expected if current[name]!=expected[name]]
    if not changed:return current,None
    if changed!=['industrial/solver.py']:raise ValueError('frozen semantics changed: '+','.join(changed))
    path=Path('provenance/analysis_compatibility.json')
    if not path.exists():raise ValueError('analysis replacement has no qualified manifest')
    manifest=read_json(path)
    if (manifest['status']!='QUALIFIED' or manifest['path']!='industrial/solver.py'
            or expected[manifest['path']]!=manifest['old_sha256'] or current[manifest['path']]!=manifest['new_sha256']):
        raise ValueError('analysis replacement fingerprint mismatch')
    root,_=fetch(manifest['qualification'],'output/compatible-analysis-qualification')
    qualification=read_json(root/'qualification.json')
    if qualification['status']!='CORE_PASS' or qualification['implementation']!=current:
        raise ValueError('replacement analysis has not passed this implementation qualification')
    return current,manifest['qualification']
