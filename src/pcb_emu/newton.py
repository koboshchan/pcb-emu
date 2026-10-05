"""Residual-tested Newton and adaptive logarithmic continuation utilities."""
import numpy as np
from scipy.sparse.linalg import spsolve


class NewtonFailure(RuntimeError):
    pass


def _residual(matrix,x,rhs):
    if hasattr(matrix,'_pcb_emu_residual'):return matrix._pcb_emu_residual
    # Accumulate high-conductance KCL cancellation with extended precision.
    # Sparse LU remains float64; this also supplies its refinement residual.
    return np.asarray(matrix.astype(np.longdouble)@x.astype(np.longdouble)-rhs.astype(np.longdouble),dtype=float)


def newton(assemble,initial,scale,max_iterations=80):
    x=initial.copy()
    for iteration in range(max_iterations):
        matrix,rhs=assemble(x,scale);residual=_residual(matrix,x,rhs)
        weights=np.maximum(np.asarray(abs(matrix).sum(axis=1)).ravel(),1e-5)
        baseline=np.linalg.norm(residual/weights)
        delta=spsolve(matrix,-residual)
        if not np.isfinite(delta).all():raise NewtonFailure('nonfinite Newton step')
        # Test the full Newton correction, never the artificially small damped step.
        # A distributed copper matrix contains large conductances. Its raw KCL
        # residual can exceed a fixed absolute threshold solely from cancellation.
        # Bound that roundoff per row without relaxing the voltage-step test.
        roundoff=64*np.finfo(float).eps*(abs(matrix)@abs(x)+abs(rhs))
        if np.max(np.abs(delta),initial=0)<1e-7 and np.all(np.abs(residual)<=1e-8+roundoff):
            return x
        alpha=1.
        for _ in range(24):
            trial=x+alpha*delta;candidate,b=assemble(trial,scale)
            merit=np.linalg.norm(_residual(candidate,trial,b)/weights)
            if np.isfinite(merit) and (merit<=(1-1e-4*alpha)*baseline or merit<1e-12):
                x=trial
                break
            alpha*=.5
        else:raise NewtonFailure(f'line search rejected residual={baseline:g}')
    raise NewtonFailure(f'iteration limit residual={baseline:g}')


def continuation(assemble,initial):
    """Keep the last converged point, subdividing failed gain steps."""
    x=newton(assemble,initial,1e-4)
    current=-4.;step=.5;failures=0
    while current<0:
        target=min(0.,current+step)
        try:
            candidate=newton(assemble,x,10**target)
        except NewtonFailure as exc:
            step*=.5;failures+=1
            if step<1e-4 or failures>80:
                raise NewtonFailure(f'gain continuation stopped scale={10**target:g}: {exc}') from exc
            continue
        x=candidate;current=target;step=min(.5,step*1.5)
    return x
