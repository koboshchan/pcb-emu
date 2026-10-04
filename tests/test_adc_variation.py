import pytest
from pcb_emu import Emulator,ADS1115,Variation


def device():
    e=Emulator();a=ADS1115().attach(e)
    e.drive(a.pin('VDD'),3.3);e.drive(a.pin('GND'),0)
    for i in range(4):e.drive(a.pin(f'A{i}'),1.)
    e.dc();a.active_config=0xc3e3
    return e,a


def test_adc_offset_gain_and_inl_stamp():
    e,a=device();a._sample();nominal=a.registers[0]
    assert nominal==8000
    a.gain_error=.001;a.offset_error=2.;a.inl_error=0;a._sample()
    assert a.registers[0]==nominal+10
    a.gain_error=0;a.offset_error=0;a.inl_error=1;a._sample()
    assert abs(a.registers[0]-nominal)<=1


def test_seeded_adc_noise():
    e,a=device();a.noise_rms=10;a.noise_seed=42;a.now=.5
    a._sample();first=a.registers[0];a._sample();assert a.registers[0]==first
    a.now=.6;a._sample();assert a.registers[0]!=first


def test_adc_parameters_in_sample_manifest():
    e,a=device();sample=Variation().apply(e,42)
    assert sample[a.board.name]['gain_error']==a.gain_error
    assert abs(a.gain_error)<=.0015 and abs(a.offset_error)<=3 and abs(a.inl_error)<=1


def test_regulator_variation():
    from pcb_emu import Board
    b=Board(name='reg',extracted={'nets':[{'node':n} for n in ('in','ground','out')],
      'components':[{'ref':'U1','value':'L7805','footprint':'Virtual:3',
        'pads':{'1':{'node':'in'},'2':{'node':'ground'},'3':{'node':'out'}}}]})
    e=Emulator();e.add_board(b);Variation().apply(e,5)
    e.drive(b.pin('U1','1'),15);e.drive(b.pin('U1','2'),0);e.dc()
    assert e.read(b.pin('U1','3'))==pytest.approx(b.components[0].regulated_voltage)
    assert 4.8<=e.read(b.pin('U1','3'))<=5.2
