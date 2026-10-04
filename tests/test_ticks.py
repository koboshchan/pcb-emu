import numpy as np
import pytest
from pcb_emu import Emulator
from test_core import circuit


def test_snapshot_immutable_and_not_reused():
    b=circuit([('R1','1k',{'1':'a','2':'g'})]);e=Emulator();e.add_board(b);e.drive(b.pin('R1','1'),1);e.drive(b.pin('R1','2'),0)
    old=e.run()
    with pytest.raises(ValueError):old.voltages[0]=9
    e.drive(b.pin('R1','1'),2);new=e.run()
    assert old['b.R1.1']==1
    assert new['b.R1.1']==2
    assert old._indices is new._indices


def test_waveform_substeps_callback_once():
    b=circuit([('R1','1k',{'1':'a','2':'b'}),('C1','1uF',{'1':'b','2':'g'})]);e=Emulator(tick=.001);e.add_board(b)
    times=[];callbacks=[]
    def voltage(t):times.append(t);return 1 if t<.0006 else 0
    e.drive(b.pin('R1','1'),voltage);e.drive(b.pin('C1','2'),0)
    e.run(1,lambda s:callbacks.append(s.tick),substeps=10)
    assert len(times)==10
    assert callbacks==[1]
    assert times[-1]==.001
    assert 0<e.read(b.pin('C1','1'))<1


def test_invalid_time_and_drive_rejected():
    with pytest.raises(ValueError):Emulator(tick=float('nan'))
    b=circuit([('R1','1k',{'1':'a','2':'g'})]);e=Emulator();e.add_board(b);e.drive(b.pin('R1','1'),float('inf'))
    with pytest.raises(ValueError):e.dc()
