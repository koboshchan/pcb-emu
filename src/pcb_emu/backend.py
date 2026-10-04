"""CPU float64 shared-matrix LU solves with NumPy and SciPy."""
import numpy as np
from scipy import linalg
import warnings


def _array(value):
    raw=np.asarray(value)
    if np.iscomplexobj(raw):raise ValueError('Only real-valued float64 circuits are supported')
    value=np.asarray(raw,dtype=np.float64)
    if not np.isfinite(value).all():raise ValueError('Inputs must be finite')
    return value


class ArrayBackend:
    """CPU shared-matrix solver. RHS and results have shape (count, N)."""
    def __init__(self,name='numpy',device=None):
        if name!='numpy' or device not in (None,'cpu'):
            raise ValueError('Only the numpy CPU backend is supported')
        self.name='numpy';self.device='cpu'

    def factor(self,A):return _Factor(A)
    def solve(self,A,B):return self.factor(A).solve(B)


class _Factor:
    def __init__(self,A):
        A=_array(A)
        if A.ndim!=2 or A.shape[0]!=A.shape[1] or not A.shape[0]:
            raise ValueError('A must be a nonempty square (N,N) matrix')
        self.n=A.shape[0]
        with warnings.catch_warnings():
            warnings.simplefilter('error',linalg.LinAlgWarning)
            try:self.lu=linalg.lu_factor(A.copy())
            except linalg.LinAlgWarning as exc:raise np.linalg.LinAlgError('Singular matrix') from exc

    def solve(self,B):
        B=_array(B)
        if B.ndim!=2 or B.shape[1]!=self.n:raise ValueError(f'B must have shape (count,{self.n})')
        if B.shape[0]==0:return np.empty(B.shape,dtype=np.float64)
        X=linalg.lu_solve(self.lu,B.T).T
        if not np.isfinite(X).all():raise np.linalg.LinAlgError('Solve produced non-finite results')
        return np.asarray(X,dtype=np.float64)
