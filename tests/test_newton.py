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


def test_large_copper_conductance_roundoff_not_false_failure():
    A=csc_matrix([[1e8+1,-1e8],[-1e8,1e8+2]])
    rhs=np.array([1.,2.])
    def assemble(x,s):return A,rhs
    result=newton(assemble,np.zeros(2),1)
    assert result==pytest.approx(np.ones(2),abs=1e-7)


def test_roundoff_tolerance_does_not_accept_large_voltage_step():
    def assemble(x,s):return csc_matrix([[1e8]]),np.array([1e8*(x[0]+1)])
    with pytest.raises(NewtonFailure):newton(assemble,np.zeros(1),1)


def test_high_conductance_opamp_feedback_converges():
    from pcb_emu import Board,Emulator
    extracted={'board':'test','nets':[{'node':n,'pads':[]} for n in ['vplus','vminus','input','out','ground']],
        'components':[{'ref':'U1','value':'TL074','footprint':'SOIC-14','pads':{p:{'node':node} for p,node in {'1':'out','2':'out','3':'input','4':'vplus','5':'ground','6':'ground','7':'ground','8':'ground','9':'ground','10':'ground','11':'vminus','12':'ground','13':'ground','14':'ground'}.items()}},
            {'ref':'J','value':'Connector','footprint':'test','pads':{'1':{'node':'input'},'2':{'node':'vplus'},'3':{'node':'vminus'},'4':{'node':'ground'}}}]}
    b=Board(name='test',extracted=extracted);e=Emulator();e.add_board(b)
    for pad,value in [('1',.5),('2',15),('3',-15),('4',0)]:e.drive(b.pin('J',pad),value)
    e._compile();out=e.aliases['out'];input_node=e.aliases['input']
    e.edges.append((out,input_node,1e-7));e.dc()
    assert e.read(b.pin('U1','1'))==pytest.approx(.5,abs=1e-6)


def test_continuation_reaches_full_gain():
    def assemble(x,s):return csc_matrix([[1.]]),np.array([s])
    assert continuation(assemble,np.zeros(1))[0]==pytest.approx(1.)
