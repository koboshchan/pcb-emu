"""Compare an actual six-bit PWM-driven first RC filter to its DC average.
Reads only the physical board's R/C pins and values. No trained data.
"""
import argparse,json
from pathlib import Path
from pcb_emu import Board,Emulator


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pcb-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    path=a.pcb_root/'two_layer/dc0_split/successor100/DC0_routed.kicad_pcb';b=Board(path,name='dc0')
    # Locate the filter only from the actual input-labelled resistor pad, then
    # follow its physical node to capacitor terminal. Labels choose stimulus,
    # but topology remains pad copper connectivity.
    candidates=[c for c in b.components if c.ref.startswith('R') and any(d.get('label')=='RAW_IN_0' for d in c.metadata['pads'].values())]
    if len(candidates)!=1:raise ValueError('Cannot identify exactly one RAW_IN_0 filter resistor')
    r=candidates[0];raw=next(p for p,d in r.metadata['pads'].items() if d.get('label')=='RAW_IN_0');other=next(p for p in r.pins if p!=raw);filtered=r.pins[other]
    caps=[c for c in b.components if c.ref.startswith('C') and filtered in c.pins.values()]
    if len(caps)!=1:raise ValueError('Cannot identify exactly one physical capacitor')
    c=caps[0];cp=next(p for p,n in c.pins.items() if n==filtered);ground=next(p for p in c.pins if p!=cp)
    period=.001;duty=31/63;dt=period/126
    # Isolate these actual PCB components for a fast filter validation. This is
    # not a full-stack transient or a substitute for inter-stage loading tests.
    sub=Board(name='filter',extracted={'components':[r.metadata,c.metadata],'nets':[{'node':n} for n in set(r.pins.values())|set(c.pins.values())]})
    e=Emulator(tick=period);e.add_board(sub)
    e.drive(sub.pin(r.ref,raw),lambda t:5. if t%period<duty*period else 0.)
    e.drive(sub.pin(c.ref,ground),0.);rows=[]
    for _ in range(150):
        for k in range(126):
            e._solve(dt,time=e.time+dt);e.time+=dt;rows.append([e.time,e.read(sub.pin(r.ref,other))])
    last=rows[-126:];mean=sum(v for t,v in last)/len(last);expected=5*duty
    result={'board':str(path),'sha256':b.extracted['sha256'],'resistor':r.ref,'R_ohm':r.resistance,'capacitor':c.ref,'C_F':c.capacitance,'period_s':period,'substep_s':dt,'duty':duty,'expected_average_V':expected,'last_cycle_average_V':mean,'error_V':mean-expected,'min_V':min(v for t,v in last),'max_V':max(v for t,v in last),'samples':rows}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='samples'},indent=2))

if __name__=='__main__':main()
