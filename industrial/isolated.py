"""Fresh-process identification with an explicit observation-file interface."""
import argparse
from pathlib import Path
from .binding import fit
from .common import actions_only,read_json,write_json,digest
from .solver import Compiled


def run():
    actions_only()
    p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('output');p.add_argument('--deadline',type=int,required=True)
    a=p.parse_args();packet=read_json(a.input)
    model,_,_=fit(packet,a.deadline)
    result=Compiled(model).solve(['execution','R'])
    write_json(a.output,dict(model=model,result=result,input_sha256=digest(Path(a.input).read_bytes())))


if __name__=='__main__':run()
