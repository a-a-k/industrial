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


def recover_and_rebind(identities,attempts,records,binder):
    """The final observable structure binds the complete retained population."""
    edges=recover(identities,records)
    return edges,[binder(attempt,edges,records) for attempt in attempts]
