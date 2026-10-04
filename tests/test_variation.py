import importlib.util
from pathlib import Path
import numpy as np
import pytest
from pcb_emu import Emulator,Variation,Board
from pcb_emu.components import Diode

spec=importlib.util.spec_from_file_location('circuits',Path(__file__).parents[1]/'examples/circuits.py')
circuits=importlib.util.module_from_spec(spec);spec.loader.exec_module(circuits)


def sample(seed):
    e=Emulator();b=e.add_board(circuits.divider());draws=Variation().apply(e,seed)
    e.drive(b.pin('R1','1'),5);e.drive(b.pin('R2','2'),0);e.dc()
    return e,b,draws


def test_deterministic_distinct_samples():
    a,b,d=sample(42);c,f,other=sample(42);g,h,third=sample(43)
    assert d==other and d!=third
    assert a.read(b.pin('R1','2'))==c.read(f.pin('R1','2'))
    assert abs(a.read(b.pin('R1','2'))-2.5)<.06
    with pytest.raises(ValueError):Variation().apply(a,42)


def test_noise_stable_at_same_time_and_changes_with_time():
    e,b,_=sample(10);e.dc();first=e.x.copy();e.dc();assert np.array_equal(first,e.x)
    e.time=.001;e.dc();assert not np.array_equal(first,e.x)


def test_opamp_parameters_and_transient():
    e=Emulator(tick=1e-5);b=e.add_board(circuits.amplifier());v=Variation(noise_bandwidth=0);v.apply(e,2)
    u=b.components[0];assert len(u.offset)==4 and u.gbw>0 and u.slew_rate>0
    for p,val in [('3',0),('4',15),('11',-15),('5',0)]:e.drive(b.pin('U1',p),val)
    e.dc();initial=e.read(b.pin('U1','1'));e.drive(b.pin('U1','3'),1)
    e.run(1);assert initial<e.read(b.pin('U1','1'))<2.1
    e.run(100);assert e.read(b.pin('U1','1'))==pytest.approx(2.,abs=.03)


def test_diode_jacobian_after_temperature_change():
    b=circuits.circuit([('D1','1N4148W',{'1':'ground','2':'input'})]);e=Emulator();e.add_board(b)
    Variation(temperature=60).apply(e,3);d=b.components[0]
    for v in [.1,.5,1.2]:
        i,s=d.current_slope(v);eps=1e-7
        fd=(d.current_slope(v+eps)[0]-d.current_slope(v-eps)[0])/(2*eps)
        assert s==pytest.approx(fd,rel=1e-5)


@pytest.mark.parametrize('kw',[{'temperature':-274},{'resistor_tolerance':1},{'noise_bandwidth':-1}])
def test_invalid_parameters(kw):
    with pytest.raises(ValueError):Variation(**kw)
