from pathlib import Path
import pytest
from pcb_emu import ADS1115, ADS1115Bus, Board, Emulator


def make_adc(addr='GND'):
    emu = Emulator()
    adc = ADS1115(addr=addr).attach(emu)
    emu.drive(adc.pin('GND'), 0)
    emu.drive(adc.pin('VDD'), 3.3)
    for channel, voltage in enumerate((1., 2., .25, 0.)):
        emu.drive(adc.pin(f'A{channel}'), voltage)
    emu.dc()
    return emu, adc


def configure(adc, now=0., mux=4, pga=1, rate=7, single=True):
    value = 0x8000 | (mux << 12) | (pga << 9) | (int(single) << 8) | (rate << 5) | 3
    adc.write(b'\x01' + value.to_bytes(2, 'big'), now)


def code(adc, now):
    adc.write(b'\x00', now)
    return int.from_bytes(adc.read(2, now), 'big', signed=True)


@pytest.mark.parametrize('rate', range(8))
def test_timing_and_stale_register(rate):
    _, adc = make_adc()
    configure(adc, rate=rate)
    assert adc.conversion_time == 1 / adc.RATES[rate]
    assert code(adc, adc.conversion_time * .99) == 0
    adc.write(b'\x01', adc.conversion_time * .99)
    assert not int.from_bytes(adc.read(2, adc.conversion_time * .99), 'big') & 0x8000
    assert code(adc, adc.conversion_time) == 8000
    adc.write(b'\x01', adc.conversion_time)
    assert int.from_bytes(adc.read(2, adc.conversion_time), 'big') & 0x8000


@pytest.mark.parametrize('pga', range(8))
def test_pga(pga):
    _, adc = make_adc()
    configure(adc, pga=pga)
    assert code(adc, 1 / 860) == min(32767, round(32768 / adc.RANGES[pga]))


@pytest.mark.parametrize('mux,voltage', [(0, -1.), (1, 1.), (2, 2.), (3, .25),
                                        (4, 1.), (5, 2.), (6, .25), (7, 0.)])
def test_mux_signed_big_endian(mux, voltage):
    _, adc = make_adc()
    configure(adc, mux=mux)
    assert code(adc, 1 / 860) == round(voltage * 8000)


@pytest.mark.parametrize('addr,address', ADS1115.ADDRESSES.items())
def test_address_and_transactions(addr, address):
    _, adc = make_adc(addr)
    now = [0.]
    bus = ADS1115Bus([adc], clock=lambda: now[0])
    assert bus('scan') == [address]
    assert bus('writeto', address, b'\x01', True) == 1
    assert bus('readfrom', address, 2, True) == b'\x85\x83'
    bus('writeto_mem', address, 1, b'\xc3\xe3', 8)
    now[0] = 1 / 860
    assert bus('readfrom_mem', address, 0, 2, 8) == b'\x1f\x40'
    bus('writeto_mem', address, 2, b'\xab\xcd', 8)
    assert bus('readfrom_mem', address, 2, 2, 8) == b'\xab\xcd'
    assert bus('readfrom', address, 1, True) == b'\xab'
    with pytest.raises(OSError):
        bus('readfrom', 0x20, 2, True)
    with pytest.raises(ValueError):
        bus('readfrom_mem', address, 0, 2, 16)


def test_bad_input_not_silently_clamped():
    emu, adc = make_adc()
    emu.drive(adc.pin('A0'), 3.8)
    emu.dc()
    configure(adc)
    with pytest.raises(ValueError, match='outside'):
        code(adc, 1 / 860)


def test_unpowered_and_collisions():
    emu, adc = make_adc()
    with pytest.raises(ValueError, match='Duplicate'):
        ADS1115Bus([adc, ADS1115('another')], clock=lambda: 0)
    bus = ADS1115Bus([adc], clock=lambda: 0)
    emu.drive(adc.pin('VDD'), 0)
    emu.dc()
    assert bus('scan') == []
    with pytest.raises(OSError):
        bus('readfrom', 0x48, 2, True)


def test_continuous_and_midconversion_config():
    _, adc = make_adc()
    configure(adc, rate=0, mux=4, single=False)
    configure(adc, now=.01, rate=7, mux=5, single=False)
    assert code(adc, .124) == 0
    assert code(adc, .125) == 8000  # old conversion retained A0, old period
    assert code(adc, .125 + 1 / 860) == 16000
    adc.write(b'\x01', .13)
    assert not int.from_bytes(adc.read(2, .13), 'big') & 0x8000


def test_comparator_and_pointer_validation():
    _, adc = make_adc()
    with pytest.raises(NotImplementedError):
        adc.write(b'\x01\xc3\xe0', 0)
    with pytest.raises(ValueError):
        adc.write(b'\x04', 0)
    assert adc.registers[1] == 0x8583
    adc.write(b'\x00\xff\xff', 0)
    assert code(adc, 0) == 0


def test_real_pico_reads_generic_adc_example():
    import importlib.util
    path = Path(__file__).parents[1] / 'examples/pico_ads1115.py'
    spec = importlib.util.spec_from_file_location('adc_example', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    emu = Emulator()
    pico, device = module.attach_readout(emu, voltage=1.25)
    try:
        emu.run(ticks=5)
        assert pico.done
        assert pico.globals['reading'] == 10000
        assert device.address == 0x48
    finally:
        pico.close()
