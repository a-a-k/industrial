import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import time

VERSION = 'industrial-observations-v1'
SEED = '20261114-industrial-e1-e6-v1'
DELTA = 5
SOURCE = 'f960b0b75b132488ddba9ec17a3b1ce77ab751db'


def actions_only():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Execution requires GitHub Actions')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def rng(*parts):
    return random.Random(int.from_bytes(hashlib.sha256('|'.join((SEED, *map(str, parts))).encode()).digest(), 'big'))


def uniform(*parts):
    return int.from_bytes(hashlib.sha256('|'.join((SEED, *map(str, parts))).encode()).digest()[:8], 'big') / 2**64


def write_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(data) + b'\n')


def read_json(path):
    return json.loads(Path(path).read_bytes())


def write_rows(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'wb') as stream:
        for row in rows:
            stream.write(canonical(row) + b'\n')


def read_rows(path):
    path = Path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def execute(command, timeout=300, env=None):
    started = time.monotonic()
    try:
        p = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
        return dict(status='OK' if p.returncode == 0 else 'FAILED', returncode=p.returncode,
                    wall_s=time.monotonic()-started, stdout=p.stdout[-3000:], stderr=p.stderr[-3000:])
    except subprocess.TimeoutExpired:
        return dict(status='TIMEOUT', wall_s=time.monotonic()-started, timeout_s=timeout)
