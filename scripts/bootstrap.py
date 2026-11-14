"""Build and hash the CPython 3.11 environment on a hosted runner."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile
from email.parser import BytesParser

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Actions only')
root = Path('output/environment'); wheels = root/'wheels'; wheels.mkdir(parents=True,exist_ok=True)
subprocess.run([sys.executable,'-m','pip','wheel','--no-cache-dir','--wheel-dir',str(wheels),
                '-r','requirements.in','-r','requirements-bdd-v1.txt'],check=True)
pins = []
for wheel in sorted(wheels.glob('*.whl')):
    with zipfile.ZipFile(wheel) as archive:
        name = next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
        metadata = BytesParser().parsebytes(archive.read(name))
    pins.append(f"{metadata['Name']}=={metadata['Version']} --hash=sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}")
(root/'requirements.lock').write_text('\n'.join(sorted(pins,key=str.lower))+'\n')
subprocess.run([sys.executable,'-m','pip','install','--no-index','--find-links',str(wheels),
                '--require-hashes','-r',str(root/'requirements.lock')],check=True)
metadata = dict(python=sys.version,run_id=os.environ['GITHUB_RUN_ID'],commit=os.environ['GITHUB_SHA'],
    wheel_files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(wheels.glob('*.whl'))})
(root/'environment.json').write_text(json.dumps(metadata,indent=2)+'\n')
with tarfile.open('output/environment.tar.gz','w:gz') as archive:
    archive.add(root,arcname='environment')
print('Hashed environment prepared')
