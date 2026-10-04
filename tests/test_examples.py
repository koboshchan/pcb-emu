from pathlib import Path
import importlib.util
import pytest
from pcb_emu import Emulator,Board

BOARDS=Path(__file__).parents[1]/'examples/boards'


def test_divider_kicad_copper():
    pytest.importorskip('pcbnew')
    b=Board(BOARDS/'divider.kicad_pcb');e=Emulator();e.add_board(b)
    e.drive(b.pin('R1','1'),5);e.drive(b.pin('R2','2'),0);e.dc()
    assert e.read(b.pin('R1','2'))==pytest.approx(2.5,abs=1e-6)
    assert not b.extracted['report']['shorts']
    assert not b.extracted['report']['split_declared_nets']


def test_amplifier_kicad_copper():
    pytest.importorskip('pcbnew')
    b=Board(BOARDS/'amplifier.kicad_pcb');e=Emulator();e.add_board(b)
    for p,v in [('3',1),('4',15),('11',-15),('5',0)]:e.drive(b.pin('U1',p),v)
    e.dc();assert e.read(b.pin('U1','1'))==pytest.approx(2,abs=.001)


def test_rc_kicad_copper_step():
    pytest.importorskip('pcbnew')
    b=Board(BOARDS/'rc_filter.kicad_pcb');e=Emulator(tick=1e-4);e.add_board(b)
    e.drive(b.pin('C1','2'),0);e.drive(b.pin('R1','1'),0);e.dc()
    e.drive(b.pin('R1','1'),5);e.run(100)
    # Backward Euler analytic result, rather than a continuum approximation.
    assert e.read(b.pin('C1','1'))==pytest.approx(5*(1-(1/1.01)**100),abs=1e-6)
