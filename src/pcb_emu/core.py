"""Programmable multi-board component simulation."""
from dataclasses import dataclass
from collections.abc import Mapping
import numpy as np
from .extract import extract_board
from .components import Capacitor, AHCT595, make_component

@dataclass(frozen=True)
class Pin:
    board: str
    ref: str
    pad: str
    node: str
    @property
    def key(self): return f'{self.board}.{self.ref}.{self.pad}'

class Board:
    def __init__(self,path=None,name='board',*,extracted=None):
        self.name=name
        self.extracted=extract_board(name,path) if extracted is None else extracted
        self.components=[make_component(self,c) for c in self.extracted['components']]
        self.pins={f'{c.ref}.{p}':Pin(name,c.ref,p,n) for c in self.components for p,n in c.pins.items()}
    def pin(self,ref,pad): return self.pins[f'{ref}.{pad}']
    def run(self,**kwargs):
        emu=Emulator(); emu.add_board(self); return emu.run(**kwargs)

class Snapshot(Mapping):
    """One immutable voltage array per tick, shared pin index map."""
    def __init__(self,tick,time,voltages,indices):
        self.tick=tick; self.time=time; self.voltages=voltages.copy()
        self.voltages.flags.writeable=False; self._indices=indices
    def __getitem__(self,key): return float(self.voltages[self._indices[key.key if isinstance(key,Pin) else key]])
    def __iter__(self): return iter(self._indices)
    def __len__(self): return len(self._indices)
    def pin(self,board,ref,pad): return self[f'{board.name if isinstance(board,Board) else board}.{ref}.{pad}']

class ConvergenceError(RuntimeError): pass

class Emulator:
    def __init__(self,tick=1e-3,*,ideal_copper=True,contact_resistance=.02,jumper_resistance=.012,temperature=20):
        if not np.isfinite(tick) or tick<=0: raise ValueError('tick must be positive and finite')
        self.tick=float(tick); self.ideal_copper=ideal_copper
        self.contact_resistance=contact_resistance; self.jumper_resistance=jumper_resistance; self.temperature=temperature
        self.supplies=[]; self.picos=[]; self.peripherals=[]; self.boards={}; self.connections=[]; self.drives={}; self.pending={}
        self.time=0.; self.tick_number=0; self._callback=False; self._compiled=False; self.cap_history={}; self._override={}
    def add_board(self,path,name=None):
        board=path if isinstance(path,Board) else Board(path,name or f'board{len(self.boards)}')
        if board.name in self.boards: raise ValueError('Duplicate board name')
        self.boards[board.name]=board; self._compiled=False; return board
    def add_psu(self,channels,name='psu',**kwargs):
        from .power import PowerSupply
        supply=PowerSupply(channels,name,**kwargs); self.add_board(supply); self.supplies.append(supply); return supply
    def add_pico(self,board=None,ref=None,code=None,**kwargs):
        from .pico import Pico
        pico=Pico(board=board,ref=ref,code=code,**kwargs); pico.attach(self); self.picos.append(pico); return pico
    def connect(self,a,b,resistance=None):
        a=self._resolve_pin(a); b=self._resolve_pin(b)
        r=self.contact_resistance if resistance is None else float(resistance)
        if not np.isfinite(r) or r<0: raise ValueError('Resistance must be finite and nonnegative')
        self.connections.append((a,b,r)); self._compiled=False
    def add_jumper(self,a,b,resistance=None): self.connect(a,b,self.jumper_resistance if resistance is None else resistance)
    def plug(self,a,header,b,socket,mapping=None):
        ap={p.pad:p for p in a.pins.values() if p.ref==header}; bp={p.pad:p for p in b.pins.values() if p.ref==socket}
        mapping={p:p for p in ap} if mapping is None else mapping
        if not ap or set(mapping)!=set(ap) or set(mapping.values())!=set(bp): raise ValueError('Connector pads do not match; pass a complete mapping')
        for p,q in mapping.items(): self.connect(ap[p],bp[q])
    def drive(self,pin,value):
        pin=self._resolve_pin(pin)
        (self.pending if self._callback else self.drives)[pin.key]=(pin,value)
    set_pin=drive
    def _resolve_pin(self,pin):
        if not isinstance(pin,Pin):
            board,ref,pad=pin.split('.'); pin=self.boards[board].pin(ref,pad)
        if pin.board not in self.boards or self.boards[pin.board].pins.get(f'{pin.ref}.{pin.pad}')!=pin: raise ValueError('Pin does not belong to this emulator')
        return pin
    def read(self,pin):
        self._compile(); return float(self.x[self.pin_indices[self._resolve_pin(pin).key]])
    def _compile(self):
        if self._compiled: return
        nodes={n['node'] for b in self.boards.values() for n in b.extracted['nets']}; parents={n:n for n in nodes}
        def root(n):
            while parents[n]!=n: parents[n]=parents[parents[n]]; n=parents[n]
            return n
        aliases={}; edges=[]; physical=set()
        if self.ideal_copper:
            for a,b,r in self.connections:
                if r==0: parents[root(b.node)]=root(a.node)
            aliases={n:root(n) for n in nodes}
            for a,b,r in self.connections:
                if r: edges.append((aliases[a.node],aliases[b.node],r))
        else:
            from .parasitics import copper_graph
            for board in self.boards.values():
                if 'copper_geometry' in board.extracted:
                    graph=copper_graph(board.extracted,temperature=self.temperature)
                    aliases.update(graph['aliases']); edges.extend(graph['edges']); physical.update(graph['nodes'])
                else:
                    # Virtual peripherals have no PCB geometry. Keep their individual terminals.
                    for p in board.pins.values(): aliases[p.node]=f'{board.name}@{p.ref}:{p.pad}'
            self._pin_nodes={p.key:f'{b.name}@{p.ref}:{p.pad}' for b in self.boards.values() for p in b.pins.values()}
            physical.update(self._pin_nodes.values())
            for a,b,r in self.connections: edges.append((self._pin_nodes[a.key],self._pin_nodes[b.key],max(r,1e-8)))
        self.nodes=sorted(set(aliases.values())|physical|{n for edge in edges for n in edge[:2]})
        self.indices={n:i for i,n in enumerate(self.nodes)}; self.aliases=aliases; self.edges=edges
        self.pin_indices={p.key:self.indices[aliases[p.node] if self.ideal_copper else self._pin_nodes[p.key]] for b in self.boards.values() for p in b.pins.values()}
        self.x=np.zeros(len(self.nodes)); self.components=[c for b in self.boards.values() for c in b.components]
        self._ci={id(c):{p:self.pin_indices[c.board.pin(c.ref,p).key] for p in c.pins} for c in self.components}; self._compiled=True
    def _digital_read(self,c,x):
        pin_nodes={n:self._ci[id(c)][p] for p,n in c.pins.items()}; return lambda n:float(x[pin_nodes[n]])
    def _solve(self,dt=None,advance=False,time=None):
        from .solver import solve
        self._compile(); t=self.time if time is None else time; drive_values={}
        for key,(pin,value) in self.drives.items():
            i=self.pin_indices[key]; v=float(value(t) if callable(value) else value)
            if not np.isfinite(v): raise ValueError('Drive must be finite')
            if i in drive_values and abs(drive_values[i]-v)>1e-8: raise ValueError('Conflicting drives on connected copper')
            drive_values[i]=v
        if advance:
            digital_x=self.x.copy()
            for i,v in drive_values.items(): digital_x[i]=v
            samples=[(c,c.sample(self._digital_read(c,digital_x))) for c in self.components if isinstance(c,AHCT595)]
            for c,sample in samples: c.advance(sample)
        self.x=solve(self,dt,t,drive_values)
        if dt:
            for c in self.components:
                if isinstance(c,Capacitor):
                    p=self._ci[id(c)]; self.cap_history[id(c)]=self.x[p['1']]-self.x[p['2']]
        for peripheral in self.peripherals: peripheral.advance(t)
        return self.x
    def dc(self): return self._solve()
    def run(self,ticks=1,callback=None,*,substeps=1):
        if int(substeps)!=substeps or substeps<1: raise ValueError('substeps must be a positive integer')
        if int(ticks)!=ticks or ticks<0: raise ValueError('ticks must be a nonnegative integer')
        self._compile(); snapshot=None
        for _ in range(ticks):
            self.drives.update(self.pending); self.pending.clear()
            for pico in self.picos: pico.advance(self.time)
            for k in range(substeps): self._solve(self.tick/substeps,advance=True,time=self.time+(k+1)*self.tick/substeps)
            self.time+=self.tick; self.tick_number+=1
            snapshot=Snapshot(self.tick_number,self.time,self.x,self.pin_indices)
            if callback:
                self._callback=True
                try: callback(snapshot)
                finally: self._callback=False
        return snapshot
