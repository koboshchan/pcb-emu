"""Full PCB stack and explicit external firmware assumptions."""
from pathlib import Path
import numpy as np
from pcb_emu import Board,Emulator
from pcb_emu.components import AHCT595


def board_paths(root,motherboard=None):
    root=Path(root)
    return {'MB':Path(motherboard) if motherboard else root/'two_layer/dc0_split/motherboard_repair/approved_bodge_CRB/post_crb.kicad_pcb','DC0':root/'two_layer/dc0_split/successor100/DC0_routed.kicad_pcb',**{f'DC1{l}':root/f'two_layer/daughtercard1{l}_weights_l1_differential_repaired.kicad_pcb' for l in 'abcd'},'DC2':root/'two_layer/daughtercard2_relu_l1_buffered_repaired.kicad_pcb','DC3':root/'two_layer/daughtercard3_weights_l2_wta_differential_repaired.kicad_pcb'}


def build_stack(root=None,motherboard=None,*,ideal_copper=True,extracted=None):
    emu=Emulator(ideal_copper=ideal_copper)
    paths=board_paths(root,motherboard) if root else {b['board']:b['path'] for b in extracted['boards']}
    for name,path in paths.items():
        board=Board(path,name,extracted=next((b for b in extracted['boards'] if b['board']==name),None) if extracted else None)
        emu.add_board(board)
    mb=emu.boards['MB']
    for name,socket in [('DC0','JD0'),('DC1a','JS0'),('DC1b','JS1'),('DC1c','JS2'),('DC1d','JS3'),('DC2','JS4'),('DC3','JS5')]:
        emu.plug(emu.boards[name],'J0' if name=='DC0' else 'J_STRADDLE_EDGE',mb,socket)
    emu.add_jumper(mb.pin('JS1','B7'),mb.pin('JS2','B7'))
    for ref,pad,value in [('JP','1',15),('JP','2',0),('JP','3',-15),('JAR','1',3.3),('JSPI','3',0),('JSPI','4',0),('JSPI','5',0),('JSPI','6',0)]:emu.drive(mb.pin(ref,pad),value)
    return emu


def area_downsample(image):
    """Exact area integration 28x28 to 8x8, row-major, no crop/inversion."""
    image=np.asarray(image,float)
    if image.shape!=(28,28):raise ValueError('Expected 28x28 MNIST image')
    edges=np.linspace(0,28,9);w=np.zeros((8,28))
    for i in range(8):
        for j in range(28):w[i,j]=max(0,min(edges[i+1],j+1)-max(edges[i],j))/(edges[i+1]-edges[i])
    return np.rint((w@image@w.T)/255*63).astype(int).ravel()


def drive_averaged_pwm(emu,pixels):
    """Explicit averaging approximation at real IC Q pins, before PCB RC loading.
    Never replaces resistor network with trained weights. Digital logic remains
    available in normal run(); DC accuracy uses these average voltage sources.
    """
    emu._compile();pixels=np.asarray(pixels,float)/63
    for c in emu.components:
        if isinstance(c,AHCT595):
            values={}
            for pad in c.q_pads:
                label=c.metadata['pads'][pad]['label']
                if not label.startswith('RAW_IN_'):raise ValueError('Unrecognized PCB output label')
                values[pad]=5*pixels[int(label.removeprefix('RAW_IN_'))]
            values['9']=0;emu._override[id(c)]=values


def classify(emu,image):
    drive_averaged_pwm(emu,area_downsample(image));emu.dc()
    mb=emu.boards['MB'];scores=np.array([emu.read(mb.pin('JS5',f'B{i+1}')) for i in range(10)])
    adc=np.array([emu.read(mb.pin('JAD',str(i+1))) for i in range(10)])
    return {'scores':scores,'adc':adc,'class':int(np.argmax(adc)),'score_class':int(np.argmax(scores))}

class ShiftRegisterStream:
    """Precomputed serial waveform with programmable sub-tick edge timing.
    bits are in serial transmission order, clocks separated from latch.
    """
    def __init__(self,bits,period=1e-5,start=0,high=3.3):
        self.bits=np.asarray(bits,dtype=int);self.period=period;self.start=start;self.high=high
    def data(self,t):
        i=int(np.floor((t-self.start)/self.period));return self.high*self.bits[i] if 0<=i<len(self.bits) else 0.
    def clock(self,t):
        q=(t-self.start)/self.period;i=int(np.floor(q));return self.high if 0<=i<len(self.bits) and q-i>=.5 else 0.
    def latch(self,t):return self.high if self.start+len(self.bits)*self.period<=t<self.start+(len(self.bits)+1)*self.period else 0.
    def attach(self,emu,data,clock,latch):
        emu.drive(data,self.data);emu.drive(clock,self.clock);emu.drive(latch,self.latch)
