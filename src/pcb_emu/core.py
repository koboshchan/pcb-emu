"""PCB component nodal solver. NumPy stamping, SciPy sparse linear algebra only."""
from dataclasses import dataclass
from collections.abc import Mapping
import numpy as np
from scipy.sparse import csc_matrix
from scipy.sparse.linalg import spsolve
from .extract import extract_board
from .components import Resistor,Capacitor,Diode,TL074,L7805,AHCT595,make_component

@dataclass(frozen=True)
class Pin:
    board: str
    ref: str
    pad: str
    node: str
    @property
    def key(self):return f'{self.board}.{self.ref}.{self.pad}'

class Board:
    def __init__(self,path=None,name='board',*,extracted=None):
        self.name=name
        self.extracted=extract_board(name,path) if extracted is None else extracted
        self.components=[make_component(self,c) for c in self.extracted['components']]
        self.pins={f'{c.ref}.{p}':Pin(name,c.ref,p,n) for c in self.components for p,n in c.pins.items()}
    def pin(self,ref,pad):return self.pins[f'{ref}.{pad}']
    def run(self,**kwargs):
        emu=Emulator();emu.add_board(self);return emu.run(**kwargs)

class Snapshot(Mapping):
    """One immutable voltage array per tick; shared pin index map, no pin dict copies."""
    def __init__(self,tick,time,voltages,indices):
        self.tick=tick;self.time=time;self.voltages=voltages.copy();self.voltages.flags.writeable=False;self._indices=indices
    def __getitem__(self,key):return float(self.voltages[self._indices[key.key if isinstance(key,Pin) else key]])
    def __iter__(self):return iter(self._indices)
    def __len__(self):return len(self._indices)
    def pin(self,board,ref,pad):return self[f'{board.name if isinstance(board,Board) else board}.{ref}.{pad}']

class ConvergenceError(RuntimeError):pass

class Emulator:
    def __init__(self,tick=1e-3,*,ideal_copper=True,contact_resistance=.02,jumper_resistance=.012,temperature=20):
        if tick<=0:raise ValueError('tick must be positive')
        self.tick=float(tick);self.ideal_copper=ideal_copper;self.contact_resistance=contact_resistance;self.jumper_resistance=jumper_resistance;self.temperature=temperature
        self.supplies=[];self.picos=[];self.boards={};self.connections=[];self.drives={};self.pending={};self.time=0.;self.tick_number=0;self._callback=False;self._compiled=False;self.cap_history={};self._override={}
    def add_board(self,path,name=None):
        board=path if isinstance(path,Board) else Board(path,name or f'board{len(self.boards)}')
        if board.name in self.boards:raise ValueError('Duplicate board name')
        self.boards[board.name]=board;self._compiled=False;return board
    def add_psu(self,channels,name='psu',**kwargs):
        from .power import PowerSupply
        supply=PowerSupply(channels,name,**kwargs);self.add_board(supply);self.supplies.append(supply);return supply
    def add_pico(self,board=None,ref=None,code=None,**kwargs):
        from .pico import Pico
        pico=Pico(board=board,ref=ref,code=code,**kwargs);pico.attach(self);self.picos.append(pico);return pico
    def connect(self,a,b,resistance=None):
        self.connections.append((a,b,self.contact_resistance if resistance is None else resistance));self._compiled=False
    def add_jumper(self,a,b,resistance=None):self.connect(a,b,self.jumper_resistance if resistance is None else resistance)
    def plug(self,a,header,b,socket,mapping=None):
        ap={p.pad:p for p in a.pins.values() if p.ref==header};bp={p.pad:p for p in b.pins.values() if p.ref==socket}
        mapping={p:p for p in ap} if mapping is None else mapping
        if set(mapping)!=set(ap) or set(mapping.values())!=set(bp):raise ValueError('Connector pad numbers do not match; pass an explicit complete mapping')
        for p,q in mapping.items():self.connect(ap[p],bp[q])
    def drive(self,pin,value):
        pin=self._resolve_pin(pin)
        (self.pending if self._callback else self.drives)[pin.key]=(pin,value)
    set_pin=drive
    def _resolve_pin(self,pin):
        if isinstance(pin,Pin):return pin
        board,ref,pad=pin.split('.');return self.boards[board].pin(ref,pad)
    def read(self,pin):
        self._compile();return float(self.x[self.pin_indices[self._resolve_pin(pin).key]])
    def _compile(self):
        if self._compiled:return
        nodes={n['node'] for b in self.boards.values() for n in b.extracted['nets']};parents={n:n for n in nodes}
        def root(n):
            while parents[n]!=n:parents[n]=parents[parents[n]];n=parents[n]
            return n
        if self.ideal_copper:
            for a,b,r in self.connections:parents[root(b.node)]=root(a.node)
            aliases={n:root(n) for n in nodes};edges=[]
        else:
            from .parasitics import copper_graph
            aliases={};edges=[]
            for board in self.boards.values():
                graph=copper_graph(board.extracted,temperature=self.temperature)
                aliases.update(graph['aliases']);edges.extend(graph['edges'])
                nodes.update(graph['nodes'])
            # Actual pads are distinct copper terminals, even on the same connected net.
            self._pin_nodes={p.key:f'{b.name}@{p.ref}:{p.pad}' for b in self.boards.values() for p in b.pins.values()}
            for a,b,r in self.connections:edges.append((self._pin_nodes[a.key],self._pin_nodes[b.key],r))
        self.nodes=sorted(set(aliases.values())|{n for e in edges for n in e[:2]});self.indices={n:i for i,n in enumerate(self.nodes)}
        self.aliases=aliases;self.edges=edges
        self.pin_indices={p.key:self.indices[aliases[p.node] if self.ideal_copper else self._pin_nodes[p.key]] for b in self.boards.values() for p in b.pins.values()}
        self.x=np.zeros(len(self.nodes));self.components=[c for b in self.boards.values() for c in b.components]
        self._ci={id(c):{p:self.pin_indices[c.board.pin(c.ref,p).key] for p in c.pins} for c in self.components}
        self._compiled=True
    def _node(self,node):return self.indices[self.aliases[node]]
    def _digital_read(self,c,x):
        pin_nodes={n:self._ci[id(c)][p] for p,n in c.pins.items()}
        return lambda n:float(x[pin_nodes[n]])
    def _solve(self,dt=None,advance=False,time=None):
        self._compile();t=self.time if time is None else time
        x=self.x.copy();N=len(x)
        drive_values={}
        for key,(pin,value) in self.drives.items():
            i=self.pin_indices[key];v=float(value(t) if callable(value) else value)
            if i in drive_values and abs(drive_values[i]-v)>1e-8:raise ValueError('Conflicting drives on connected copper')
            drive_values[i]=v
        # Sample all digital ICs from one old-state snapshot plus current external inputs.
        digital_x=x.copy()
        for i,v in drive_values.items():digital_x[i]=v
        if advance:
            samples=[(c,c.sample(self._digital_read(c,digital_x))) for c in self.components if isinstance(c,AHCT595)]
            for c,sample in samples:c.advance(sample)
        # Mild gain continuation avoids a huge discontinuity when starting from zero.
        for gain_scale in ([.001,.01,.1,1.] if np.max(np.abs(x),initial=0)<1e-10 else [1.]):
            for iteration in range(160):
                rows=[];cols=[];vals=[];rhs=np.zeros(N);constraints={}
                def entry(a,b,v):rows.append(a);cols.append(b);vals.append(v)
                for i in range(N):entry(i,i,1e-12)
                def conduct(a,b,g,current=0.):
                    entry(a,a,g);entry(b,b,g);entry(a,b,-g);entry(b,a,-g);rhs[a]-=current;rhs[b]+=current
                for a,b,r in self.edges:conduct(self.indices[a],self.indices[b],1/max(r,1e-8))
                for supply in self.supplies:supply.stamp(conduct,x,self.pin_indices,t)
                for c in self.components:
                    p=self._ci[id(c)]
                    if isinstance(c,Resistor):conduct(p['1'],p['2'],1/max(c.resistance,1e-6))
                    elif isinstance(c,Capacitor) and dt:
                        g=c.capacitance/dt;old=self.cap_history.get(id(c),0.);conduct(p['1'],p['2'],g,-g*old)
                    elif isinstance(c,Diode):
                        a,b=p['2'],p['1'];v=x[a]-x[b];current,g=c.current_slope(v);conduct(a,b,g,current-g*v)
                    elif isinstance(c,TL074):
                        for op,mi,pl in [('1','2','3'),('7','6','5'),('8','9','10'),('14','13','12')]:
                            out,minus,plus=p[op],p[mi],p[pl];gain=c.gain*gain_scale
                            lo=x[p['11']]+c.headroom;hi=x[p['4']]-c.headroom
                            if hi<lo:lo=hi=(x[p['11']]+x[p['4']])/2
                            center=(hi+lo)/2;span=max((hi-lo)/2,1e-6)
                            z=(gain*(x[plus]-x[minus])-center)/span
                            tanh=np.tanh(z);target=center+span*tanh;derivative=gain*(1-tanh*tanh)
                            co={}
                            for i,v in [(out,1.),(plus,-derivative),(minus,derivative)]:co[i]=co.get(i,0)+v
                            constraints[out]=(co,target-derivative*(x[plus]-x[minus]))
                    elif isinstance(c,L7805):
                        vi=x[p['1']]-x[p['2']]
                        if vi>=7:constraints[p['3']]=({p['3']:1,p['2']:-1},5.)
                        elif vi>=2:constraints[p['3']]=({p['3']:1,p['1']:-1},-2.)
                        else:constraints[p['3']]=({p['3']:1,p['2']:-1},0.)
                    elif isinstance(c,AHCT595):
                        if id(c) not in self._override:
                            for node,v in c.outputs(self._digital_read(c,x)).items():
                                i=next(p[pad] for pad,n in c.pins.items() if n==node);constraints[i]=({i:1.},v)
                        else:
                            for pad,v in self._override[id(c)].items():constraints[p[pad]]=({p[pad]:1.},float(v))
                for i,v in drive_values.items():constraints[i]=({i:1.},v)
                keep=[j for j,r in enumerate(rows) if r not in constraints]
                rr=[rows[j] for j in keep];cc=[cols[j] for j in keep];vv=[vals[j] for j in keep]
                for r,(co,value) in constraints.items():
                    rhs[r]=value
                    for col,val in co.items():rr.append(r);cc.append(col);vv.append(val)
                matrix=csc_matrix((vv,(rr,cc)),shape=(N,N))
                nxt=spsolve(matrix,rhs)
                if not np.isfinite(nxt).all():raise ConvergenceError('Nonfinite nodal solution')
                delta=nxt-x
                # Diode junction voltage limiting, not a global rail ramp.
                max_d=max((abs(delta[self._ci[id(c)]['2']]-delta[self._ci[id(c)]['1']]) for c in self.components if isinstance(c,Diode)),default=0.)
                damping=min(1.,.2/max_d) if max_d else 1.
                x=x+damping*delta
                if np.max(np.abs(delta),initial=0)<2e-7:break
            else:raise ConvergenceError(f'Newton failed after {iteration+1} iterations at t={t:g}, max delta={np.max(np.abs(delta)):g}')
        self.x=x
        if dt:
            for c in self.components:
                if isinstance(c,Capacitor):
                    p=self._ci[id(c)];self.cap_history[id(c)]=x[p['1']]-x[p['2']]
        return x
    def dc(self):return self._solve()
    def run(self,ticks=1,callback=None,*,substeps=1):
        if int(substeps)!=substeps or substeps<1:raise ValueError('substeps must be a positive integer')
        self._compile();snapshot=None
        for _ in range(ticks):
            for pico in self.picos:pico.advance(Snapshot(self.tick_number,self.time,self.x,self.pin_indices))
            self.drives.update(self.pending);self.pending.clear()
            for k in range(substeps):
                self._solve(self.tick/substeps,advance=True,time=self.time+(k+1)*self.tick/substeps)
            self.time+=self.tick;self.tick_number+=1
            snapshot=Snapshot(self.tick_number,self.time,self.x,self.pin_indices)
            if callback:
                self._callback=True
                try:callback(snapshot)
                finally:self._callback=False
        return snapshot
