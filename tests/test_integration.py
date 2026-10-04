import numpy as np
from pcb_emu import Emulator
from test_core import circuit


def test_psu_cv_load():
    load=circuit([('R1','100',{'1':'plus','2':'ground'})])
    e=Emulator();e.add_board(load);p=e.add_psu({'ch':5},current_limit=.1,output_resistance=.1)
    e.connect(p.pin('ch+'),load.pin('R1','1'),resistance=0)
    e.connect(p.pin('ch-'),load.pin('R1','2'),resistance=0)
    e.drive(p.pin('ch-'),0);p.on();e.dc()
    assert abs(e.read(load.pin('R1','1'))-5*100/100.1)<1e-7
    assert p.channels['ch']['mode']=='CV'
    assert abs(p.channels['ch']['current']-5/100.1)<1e-7


def test_psu_current_limit():
    load=circuit([('R1','10',{'1':'plus','2':'ground'})])
    e=Emulator();e.add_board(load);p=e.add_psu({'ch':5},current_limit=.1)
    e.connect(p.pin('ch+'),load.pin('R1','1'),resistance=0)
    e.connect(p.pin('ch-'),load.pin('R1','2'),resistance=0)
    e.drive(p.pin('ch-'),0);p.on();e.dc()
    assert abs(e.read(load.pin('R1','1'))-1)<1e-6
    assert p.channels['ch']['mode']=='CC'


def test_actual_pico_executor():
    e=Emulator();p=e.add_pico(source='from machine import Pin\nfrom time import sleep_ms\np=Pin(0,Pin.OUT,value=1)\nsleep_ms(2)\np.off()')
    try:
        e.run(1);assert e.read(p.pin(0))==3.3
        e.run(2);assert e.read(p.pin(0))==0
        assert p.done
    finally:p.close()


def test_contact_resistance_even_ideal_copper():
    a=circuit([('R1','10',{'1':'load','2':'ground'})]);e=Emulator();e.add_board(a)
    p=e.add_psu({'ch':5},current_limit=1,output_resistance=.001)
    e.connect(p.pin('ch+'),a.pin('R1','1'),resistance=1)
    e.connect(p.pin('ch-'),a.pin('R1','2'),resistance=0)
    e.drive(p.pin('ch-'),0);p.on();e.dc()
    assert abs(e.read(a.pin('R1','1'))-50/11.001)<1e-6
