"""Verified transfer of immutable public experiment release assets."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile


def fetch(tag,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    repo=os.environ['GITHUB_REPOSITORY']
    def download(name):
        subprocess.run(['gh','release','download',tag,'--repo',repo,'--pattern',name,'--dir',str(folder),'--clobber'],check=True)
    download('*.receipt.json')
    receipts=list(folder.glob('*.receipt.json'))
    if len(receipts)!=1:raise ValueError('ambiguous release receipt')
    receipt=json.loads(receipts[0].read_bytes());parts=[]
    for part in receipt['parts']:
        download(part['name']);path=folder/part['name']
        if path.stat().st_size!=part['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=part['sha256']:
            raise ValueError('release part checksum mismatch')
        parts.append(path)
    archive=folder/'verified.tar.gz'
    with archive.open('wb') as dst:
        for part in parts:
            with part.open('rb') as src:
                while block:=src.read(1024**2):dst.write(block)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=receipt['archive_sha256']:
        raise ValueError('release archive checksum mismatch')
    with tarfile.open(archive,'r:gz') as tar:
        tar.extractall(folder,filter='data')
    root=folder/receipt['name']
    manifest=json.loads((root/'SHA256SUMS.json').read_bytes())
    for name,expected in manifest.items():
        path=(root/name).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('release file checksum mismatch')
    return root,receipt
