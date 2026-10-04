"""Run a reproducible PCB-only averaged-PWM MNIST test.
Pass a pcbai checkout and MNIST IDX gzip files. No design/weights scripts read.
"""
import argparse,gzip,json,struct,time
from pathlib import Path
import numpy as np
from mnist_stack import build_stack,classify

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pcb-root',type=Path)
    p.add_argument('--extracted',type=Path)
    p.add_argument('--motherboard',type=Path)
    p.add_argument('--images',type=Path,required=True)
    p.add_argument('--labels',type=Path,required=True)
    p.add_argument('--count',type=int,default=1000)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    extracted=json.loads(a.extracted.read_text()) if a.extracted else None
    e=build_stack(a.pcb_root,a.motherboard,extracted=extracted)
    images=gzip.decompress(a.images.read_bytes());labels=gzip.decompress(a.labels.read_bytes())
    magic,n,h,w=struct.unpack('>4I',images[:16]);lmagic,ln=struct.unpack('>2I',labels[:8])
    if (magic,lmagic,h,w)!=(2051,2049,28,28) or n!=ln:raise ValueError('Invalid MNIST IDX')
    imgs=np.frombuffer(images[16:],np.uint8).reshape(n,h,w);truth=np.frombuffer(labels[8:],np.uint8)
    rows=[];start=time.perf_counter();good=0
    for i in range(min(a.count,n)):
        try:
            result=classify(e,imgs[i]);row={'index':i,'label':int(truth[i]),'prediction':result['class'],'score_prediction':result['score_class'],'scores':result['scores'].tolist(),'adc':result['adc'].tolist()}
            good+=row['prediction']==row['label']
        except Exception as ex:row={'index':i,'label':int(truth[i]),'error':type(ex).__name__+': '+str(ex)}
        rows.append(row)
        if (i+1)%25==0:print(i+1,good,round(time.perf_counter()-start,2),flush=True)
    count=len(rows);failures=sum('error' in r for r in rows)
    report={'count':count,'correct':good,'accuracy':good/count if count else None,'solver_failures':failures,'seconds':time.perf_counter()-start,'mode':'ideal copper, average PWM, explicit IN38 jumper, finite-gain TL074 with 50ohm output behavioral resistance','input_mapping':'28x28 exact area average to8x8,row-major,6bit,no inversion','board_sources':[{'name':b.name,'path':b.extracted.get('path'),'sha256':b.extracted.get('sha256')} for b in e.boards.values()],'samples':rows}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2))

if __name__=='__main__':main()
