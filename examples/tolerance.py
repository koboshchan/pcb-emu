"""Seeded PCB-value tolerance evaluation, without training or retuning."""
import argparse,json,gzip
from pathlib import Path
import numpy as np
from mnist_stack import build_stack,classify
from pcb_emu.components import Resistor,Capacitor


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--extracted',type=Path,required=True);p.add_argument('--images',type=Path,required=True);p.add_argument('--index',type=int,default=0);p.add_argument('--runs',type=int,default=10);p.add_argument('--tolerance',type=float,default=.01);p.add_argument('--seed',type=int,default=42);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    x=json.loads(a.extracted.read_text());e=build_stack(extracted=x);e._compile();raw=gzip.decompress(a.images.read_bytes());image=np.frombuffer(raw[16:],np.uint8).reshape(-1,28,28)[a.index]
    parameters=[(c,'resistance',c.resistance) if isinstance(c,Resistor) else (c,'capacitance',c.capacitance) for c in e.components if isinstance(c,(Resistor,Capacitor))]
    rng=np.random.default_rng(a.seed);rows=[]
    for i in range(a.runs):
        for c,attr,value in parameters:setattr(c,attr,value*(1+rng.uniform(-a.tolerance,a.tolerance)))
        result=classify(e,image);rows.append({'iteration':i,'prediction':result['class'],'adc':result['adc'].tolist()})
    report={'image_index':a.index,'runs':a.runs,'seed':a.seed,'uniform_relative_tolerance':a.tolerance,'mode':'DC average PWM, ideal copper with finite contacts; capacitor variation has no effect in DC; no tuning','samples':rows}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
