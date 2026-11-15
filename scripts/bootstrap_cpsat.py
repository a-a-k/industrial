"""Freeze a separate binary-only OR-Tools environment on Actions."""
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
root=Path('output/cpsat-environment');wheels=root/'wheels';wheels.mkdir(parents=True,exist_ok=True)
subprocess.run([sys.executable,'-m','pip','download','--no-cache-dir','--only-binary=:all:',
    '--dest',str(wheels),'ortools==9.15.6755'],check=True)
pins=[];files={}
for wheel in sorted(wheels.glob('*.whl')):
    with zipfile.ZipFile(wheel) as archive:
        name=next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
        metadata=BytesParser().parsebytes(archive.read(name))
    sha=hashlib.sha256(wheel.read_bytes()).hexdigest();files[wheel.name]=sha
    pins.append(f"{metadata['Name']}=={metadata['Version']} --hash=sha256:{sha}")
(root/'requirements.lock').write_text('\n'.join(sorted(pins,key=str.lower))+'\n')
(root/'environment.json').write_text(json.dumps(dict(python=sys.version,ortools='9.15.6755',
    wheel_files=files,commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
    isolation='separate virtual environment; original scientific environment unchanged'),indent=2)+'\n')
