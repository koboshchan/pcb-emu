"""Small explicit behavioral models, not manufacturer-grade silicon models."""
import re
import numpy as np


def number(value):
    text=value.strip().replace('Ω','').replace('ohm','').replace('µ','u').replace('μ','u')
    text=re.sub(r'[FV]$', '', text)
    m=re.fullmatch(r'([\d.]+)\s*([pnumkKMG]?)(?:[Rr])?',text)
    if not m:
        m=re.fullmatch(r'(\d+)([RrKkMm])(\d+)',text)
        if m:return float(m[1]+'.'+m[3])*{'R':1,'r':1,'K':1e3,'k':1e3,'M':1e6,'m':1e-3}[m[2]]
        raise ValueError(f'Unrecognized component value {value!r}')
    return float(m[1])*{'':1,'p':1e-12,'n':1e-9,'u':1e-6,'m':1e-3,'k':1e3,'K':1e3,'M':1e6,'G':1e9}[m[2]]

class Component:
    def __init__(self, board, metadata):
        self.board=board;self.ref=metadata['ref'];self.value=metadata['value'];self.metadata=metadata
        self.pins={p:d['node'] for p,d in metadata['pads'].items()}

class Connector(Component):pass
class MountingHole(Component):pass
class Resistor(Component):
    def __init__(self,*a):
        super().__init__(*a);self.resistance=number(self.value)
class Capacitor(Component):
    def __init__(self,*a):
        super().__init__(*a);self.capacitance=number(self.value.split()[0])
class Diode(Component):
    def __init__(self,*a):
        super().__init__(*a);self.anode=self.pins['2'];self.cathode=self.pins['1'];self.isat=2.52e-9;self.nvt=.045
    def current_slope(self,v):
        # Exponential with linear extension above 0.9 V to keep Newton finite.
        z=np.minimum(v/self.nvt,20.);e=np.exp(z)
        slope=self.isat/self.nvt*e
        current=self.isat*(e-1)+slope*np.maximum(v-.9,0)
        return current,slope
class TL074(Component):
    def __init__(self,*a):
        super().__init__(*a)
        self.channels=[tuple(self.pins[str(p)] for p in pins) for pins in [(1,2,3),(7,6,5),(8,9,10),(14,13,12)]]
        self.vplus=self.pins['4'];self.vminus=self.pins['11'];self.gain=1e5;self.headroom=1.5
class L7805(Component):
    def target(self,read):
        g=read(self.pins['2']);return g+np.clip(read(self.pins['1'])-g-2,0,5)
class AHCT595(Component):
    q_pads=('15','1','2','3','4','5','6','7')
    def __init__(self,*a):
        super().__init__(*a);self.shift=0;self.latch=0;self.previous_clock=False;self.previous_latch=False
    def sample(self,read):
        g=read(self.pins['8']);high=lambda p:read(self.pins[p])-g>=2.0
        return high('11'),high('12'),high('10'),high('14')
    def advance(self,sample):
        clock,latch,clear,data=sample;old=self.shift
        if not clear:self.shift=0
        elif clock and not self.previous_clock:self.shift=((self.shift<<1)|int(data))&255
        if latch and not self.previous_latch:self.latch=old
        self.previous_clock=clock;self.previous_latch=latch
    def outputs(self,read):
        lo=read(self.pins['8']);hi=read(self.pins['16']);outputs={self.pins['9']:hi if self.shift&128 else lo}
        if hi-lo<1:return {node:lo for node in outputs}
        if read(self.pins['13'])-lo<.8:
            outputs.update({self.pins[p]:hi if self.latch&(1<<i) else lo for i,p in enumerate(self.q_pads)})
        return outputs
class PicoADC(Connector):
    """External ADC interface on connector, not invented MCU firmware."""
    def convert(self,voltage,reference=3.3,bits=12):
        return np.rint(np.clip(np.asarray(voltage)/reference,0,1)*(2**bits-1)).astype(int)


def make_component(board,metadata):
    value=metadata['value'];ref=metadata['ref'];footprint=metadata['footprint']
    if ref.startswith('R'):kind=Resistor
    elif ref.startswith('C'):kind=Capacitor
    elif value=='1N4148W':kind=Diode
    elif value=='TL074':kind=TL074
    elif value.startswith('74AHCT595'):kind=AHCT595
    elif value.startswith('L7805'):kind=L7805
    elif ref=='JAD' and 'ADC' in ' '.join(p['label'] for p in metadata['pads'].values()):kind=PicoADC
    elif ref.startswith('J'):kind=Connector
    elif 'MountingHole' in value or not metadata['pads']:kind=MountingHole
    else:raise ValueError(f'Unsupported component {board.name}.{ref} {value} {footprint}')
    return kind(board,metadata)
