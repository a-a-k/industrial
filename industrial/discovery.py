"""Recovery from accepted relations; the true adjacency is not an input."""
from .model import Unsupported


def recover(identities, records):
    identities=set(identities);edges=set()
    for record in records:
        source,target=record['source'],record['target']
        if source not in identities or target not in identities:
            raise Unsupported('unexplained required boundary')
        edges.add((source,target))
    return sorted(edges)
