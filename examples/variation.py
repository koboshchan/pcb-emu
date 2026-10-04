"""Seeded divider Monte Carlo, always use fresh boards per physical sample."""
import argparse
import numpy as np
from pcb_emu import Emulator,Variation
from circuits import divider


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--samples',type=int,default=100)
    p.add_argument('--seed',type=int,default=42)
    args=p.parse_args()
    if args.samples<1:p.error('samples must be positive')
    values=[]
    for seed in range(args.seed,args.seed+args.samples):
        e=Emulator();b=e.add_board(divider())
        Variation().apply(e,seed)
        e.drive(b.pin('R1','1'),5);e.drive(b.pin('R2','2'),0);e.dc()
        values.append(e.read(b.pin('R1','2')))
    print('Output volts, mean/std/min/max',np.mean(values),np.std(values),min(values),max(values))

if __name__=='__main__':main()
