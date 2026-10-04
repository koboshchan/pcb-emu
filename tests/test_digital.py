from pcb_emu import Emulator
from test_core import circuit
from pcb_emu.components import AHCT595


def test_shift_latch_and_output_enable():
    pins={'1':'q1','2':'q2','3':'q3','4':'q4','5':'q5','6':'q6','7':'q7','8':'g','9':'serial','10':'clear','11':'clk','12':'latch','13':'oe','14':'data','15':'q0','16':'v'}
    b=circuit([('U1','74AHCT595',pins)]);e=Emulator();e.add_board(b)
    for p,v in [('8',0),('16',5),('10',3.3),('11',0),('12',0),('13',0),('14',0)]:e.drive(b.pin('U1',p),v)
    e.dc()
    for bit in [1,0,1,0,0,1,0,1]:
        e.drive(b.pin('U1','14'),3.3*bit);e.drive(b.pin('U1','11'),0);e._solve(advance=True)
        e.drive(b.pin('U1','11'),3.3);e._solve(advance=True)
    e.drive(b.pin('U1','11'),0);e._solve(advance=True)
    assert b.components[0].shift==0b10100101
    assert b.components[0].latch==0
    e.drive(b.pin('U1','12'),3.3);e._solve(advance=True)
    assert b.components[0].latch==0b10100101
    assert [round(e.read(b.pin('U1',p))) for p in AHCT595.q_pads]==[5,0,5,0,0,5,0,5]
    e.drive(b.pin('U1','10'),0);e._solve(advance=True)
    assert b.components[0].shift==0
    assert b.components[0].latch==0b10100101  # clear affects shift, not storage


def test_cascade_samples_old_serial_value():
    def pins(prefix,serial_input,serial_output):
        d={str(i):prefix+str(i) for i in range(1,17)}
        d.update({'8':'g','16':'v','10':'clear','11':'clk','12':'latch','13':'oe','14':serial_input,'9':serial_output})
        return d
    b=circuit([('U1','74AHCT595',pins('a','data','wire')),('U2','74AHCT595',pins('b','wire','out'))]);e=Emulator();e.add_board(b)
    for p,v in [('8',0),('16',5),('10',3.3),('11',0),('12',0),('13',0),('14',0)]:e.drive(b.pin('U1',p),v)
    first,second=b.components;first.shift=0b10000000;e.dc()
    e.drive(b.pin('U1','11'),3.3);e._solve(advance=True)
    assert first.shift==0
    assert second.shift==1
