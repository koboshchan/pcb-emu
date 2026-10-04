"""Analytic, residual-tested damped Newton with gain continuation."""
import numpy as np
from scipy.sparse import csc_matrix
from scipy.sparse.linalg import spsolve
from .components import Resistor,Capacitor,Diode,TL074,L7805,AHCT595


def solve(emulator,dt,time,drive_values):
    e=emulator;N=len(e.x);x=e.x.copy()
    def assemble(x,gain_scale):
        rows=[];cols=[];vals=[];rhs=np.zeros(N);constraints={}
        def entry(a,b,v):rows.append(a);cols.append(b);vals.append(v)
        for i in range(N):entry(i,i,1e-12)
        def conduct(a,b,g,current=0.):
            entry(a,a,g);entry(b,b,g);entry(a,b,-g);entry(b,a,-g);rhs[a]-=current;rhs[b]+=current
        for a,b,r in e.edges:conduct(e.indices[a],e.indices[b],1/max(r,1e-8))
        for supply in e.supplies:supply.stamp(conduct,x,e.pin_indices,time)
        for c in e.components:
            p=e._ci[id(c)]
            if isinstance(c,Resistor):conduct(p['1'],p['2'],1/max(c.resistance,1e-6))
            elif isinstance(c,Capacitor) and dt:
                g=c.capacitance/dt;conduct(p['1'],p['2'],g,-g*e.cap_history.get(id(c),0.))
            elif isinstance(c,Diode):
                a,b=p['2'],p['1'];v=x[a]-x[b];current,g=c.current_slope(v);conduct(a,b,g,current-g*v)
            elif isinstance(c,TL074):
                for op,mi,pl in [('1','2','3'),('7','6','5'),('8','9','10'),('14','13','12')]:
                    out,minus,plus=p[op],p[mi],p[pl];gain=c.gain*gain_scale
                    lo=x[p['11']]+c.headroom;hi=x[p['4']]-c.headroom
                    span=max((hi-lo)/2,1e-3);center=(hi+lo)/2
                    z=(gain*(x[plus]-x[minus])-center)/span;tanh=np.tanh(z);target=center+span*tanh;derivative=gain*(1-tanh*tanh)
                    # Finite output impedance makes this a KCL branch, not an ideal row replacement.
                    go=1/50.
                    entry(out,out,go);entry(out,plus,-go*derivative);entry(out,minus,go*derivative)
                    rhs[out]+=go*(target-derivative*(x[plus]-x[minus]))
            elif isinstance(c,L7805):
                vi=x[p['1']]-x[p['2']]
                if vi>=7:constraints[p['3']]=({p['3']:1,p['2']:-1},5.)
                elif vi>=2:constraints[p['3']]=({p['3']:1,p['1']:-1},-2.)
                else:constraints[p['3']]=({p['3']:1,p['2']:-1},0.)
            elif isinstance(c,AHCT595):
                if id(c) not in e._override:
                    for node,v in c.outputs(e._digital_read(c,x)).items():
                        i=next(p[pad] for pad,n in c.pins.items() if n==node);constraints[i]=({i:1.},v)
                else:
                    for pad,v in e._override[id(c)].items():constraints[p[pad]]=({p[pad]:1.},float(v))
        for i,v in drive_values.items():constraints[i]=({i:1.},v)
        keep=[j for j,r in enumerate(rows) if r not in constraints]
        rr=[rows[j] for j in keep];cc=[cols[j] for j in keep];vv=[vals[j] for j in keep]
        for r,(co,value) in constraints.items():
            rhs[r]=value
            for col,val in co.items():rr.append(r);cc.append(col);vv.append(val)
        A=csc_matrix((vv,(rr,cc)),shape=(N,N));return A,rhs
    if np.max(np.abs(x),initial=0)>1e-8:
        # A previous accepted operating point is usually an excellent warm start.
        try:
            for iteration in range(35):
                A,b=assemble(x,1.);residual=A@x-b
                weights=np.maximum(np.asarray(abs(A).sum(axis=1)).ravel(),1e-5)
                baseline=np.linalg.norm(residual/weights);delta=spsolve(A,-residual)
                if not np.isfinite(delta).all():break
                alpha=1.
                for backtrack in range(24):
                    trial=x+alpha*delta;At,bt=assemble(trial,1.)
                    merit=np.linalg.norm((At@trial-bt)/weights)
                    if merit<=(1-1e-4*alpha)*baseline or merit<1e-10:break
                    alpha*=.5
                x=trial
                if np.max(np.abs(alpha*delta),initial=0)<1e-7 and merit<1e-8:
                    for supply in e.supplies:supply.stamp(lambda *a:None,x,e.pin_indices,time)
                    return x
        except (ValueError,RuntimeError):pass
        x=e.x.copy()
    for scale in [1e-4,1e-3,1e-2,.1,1.]:
        for iteration in range(100):
            A,b=assemble(x,scale);residual=A@x-b
            # Fixed residual scaling within this Newton step; no derivative-based fake decrease.
            weights=np.maximum(np.asarray(abs(A).sum(axis=1)).ravel(),1e-5)
            baseline=np.linalg.norm(residual/weights)
            delta=spsolve(A,-residual)
            if not np.isfinite(delta).all():raise RuntimeError('Nonfinite Newton step')
            alpha=1.
            for backtrack in range(24):
                trial=x+alpha*delta;At,bt=assemble(trial,scale)
                merit=np.linalg.norm((At@trial-bt)/weights)
                if merit<=(1-1e-4*alpha)*baseline or merit<1e-10:break
                alpha*=.5
            x=trial
            if np.max(np.abs(alpha*delta),initial=0)<1e-7 and merit<1e-8:break
        else:
            from .core import ConvergenceError
            raise ConvergenceError(f'Newton failed scale={scale:g} residual={merit:g} at t={time:g}')
    # Refresh supply meter at accepted final solution.
    for supply in e.supplies:supply.stamp(lambda *a:None,x,e.pin_indices,time)
    return x
