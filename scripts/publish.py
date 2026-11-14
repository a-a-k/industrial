"""Upload complete public evidence directly to Releases with bounded assets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
p=argparse.ArgumentParser();p.add_argument('--name',required=True);p.add_argument('--path',required=True)
a=p.parse_args(); root=Path(a.path).resolve(); workspace=Path.cwd().resolve()
if not root.is_relative_to(workspace) or '.private' in root.parts:
    raise SystemExit('Not a public evidence directory')
files=[f for f in root.rglob('*') if f.is_file()]
if any('.private' in f.parts or f.suffix in ('.pem','.key') for f in files):
    raise SystemExit('Private material in evidence selection')
manifest={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
(root/'SHA256SUMS.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
base=f"{a.name}-{os.environ['GITHUB_RUN_ID']}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}"
archive=Path('output')/(base+'.tar.gz');archive.parent.mkdir(exist_ok=True)
with tarfile.open(archive,'w:gz') as tar:tar.add(root,arcname=a.name)
chunk=1024**3; parts=[]
if archive.stat().st_size >= chunk:
    with archive.open('rb') as stream:
        index=0
        while data:=stream.read(chunk):
            part=archive.with_name(archive.name+f'.part{index:04d}');part.write_bytes(data);parts.append(part);index+=1
else:parts=[archive]
receipt=archive.with_suffix('.receipt.json')
receipt.write_text(json.dumps(dict(name=a.name,commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
    archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    parts=[dict(name=f.name,bytes=f.stat().st_size,sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in parts]),indent=2))
parts.append(receipt)
for start in range(0,len(parts),900):
    selected=parts[start:start+900];tag=base+(f'-volume{start//900:03d}' if start else '')
    subprocess.run(['gh','release','create',tag,*map(str,selected),'--target',os.environ['GITHUB_SHA'],
        '--prerelease','--title',base,'--notes','Versioned experimental evidence. See protocol and SHA256SUMS.json.'],check=True)
print(base)
