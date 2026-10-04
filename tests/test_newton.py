import numpy as np
import pytest
from scipy.sparse import csc_matrix
from pcb_emu.newton import newton,NewtonFailure,continuation


def test_linear_solution():
    def assemble(x,s):return csc_matrix([[2.]]),np.array([6.])
    assert newton(assemble,np.zeros(1),1)[0]==pytest.approx(3.)


def test_failed_line_search_is_rejected():
    def assemble(x,s):
        # Constant impossible residual, deliberately inconsistent Jacobian.
        return csc_matrix([[1.]]),np.array([x[0]-1])
    with pytest.raises(NewtonFailure,match='line search rejected'):newton(assemble,np.zeros(1),1)


def test_continuation_reaches_full_gain():
    def assemble(x,s):return csc_matrix([[1.]]),np.array([s])
    assert continuation(assemble,np.zeros(1))[0]==pytest.approx(1.)
