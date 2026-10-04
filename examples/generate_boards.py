"""Generate self-made copper-connectivity fixtures, not fabrication layouts.

Pads on separate horizontal buses avoid unintended intersections. Component
pad spacings are intentionally schematic-like, not manufacturer footprints.
Requires KiCad pcbnew. Writes only to the requested output directory.
"""
import argparse
from pathlib import Path
from circuits import divider,rc,amplifier


def save(board,path):
    import pcbnew as p
    pcb=p.BOARD()
    labels=sorted({d['label'] for c in board.extracted['components'] for d in c['pads'].values()})
    nets={};points={}
    for i,label in enumerate(labels):
        net=p.NETINFO_ITEM(pcb,label);pcb.Add(net);nets[label]=net;points[label]=[]
    for i,c in enumerate(board.extracted['components']):
        fp=p.FOOTPRINT(pcb);fp.SetReference(c['ref']);fp.SetValue(c['value']);pcb.Add(fp)
        for j,(number,data) in enumerate(c['pads'].items()):
            label=data['label'];x=5+i*12+j*.6;y=5+labels.index(label)*4
            pad=p.PAD(fp);pad.SetNumber(number);pad.SetAttribute(p.PAD_ATTRIB_SMD)
            pad.SetShape(p.PAD_SHAPE_RECT);pad.SetSize(p.VECTOR2I(400000,400000))
            pad.SetPosition(p.VECTOR2I(int(x*1e6),int(y*1e6)))
            layers=p.LSET();layers.AddLayer(p.F_Cu);pad.SetLayerSet(layers)
            pad.SetNet(nets[label]);fp.Add(pad);points[label].append((x,y))
    for label,xy in points.items():
        xy.sort()
        for a,b in zip(xy,xy[1:]):
            track=p.PCB_TRACK(pcb);track.SetStart(p.VECTOR2I(int(a[0]*1e6),int(a[1]*1e6)))
            track.SetEnd(p.VECTOR2I(int(b[0]*1e6),int(b[1]*1e6)))
            track.SetWidth(200000);track.SetLayer(p.F_Cu);track.SetNet(nets[label]);pcb.Add(track)
    p.SaveBoard(str(path),pcb)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,default=Path(__file__).parent/'boards');args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    for name,make in [('divider',divider),('rc_filter',rc),('amplifier',amplifier)]:save(make(),args.out/(name+'.kicad_pcb'))

if __name__=='__main__':main()
