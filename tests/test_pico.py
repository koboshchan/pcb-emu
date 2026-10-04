"""Run with the same KiCad-enabled Python environment as core.py."""
import sys
import unittest
from pcb_emu.pico import Pico, GPIO_PADS, PAD_NAMES

class MockEmulator:
    def __init__(self):self.boards={};self.drives={};self.pending={};self.voltages={}
    def add_board(self,b):self.boards[b.name]=b
    def drive(self,p,v):self.drives[p.key]=(p,v);self.voltages[p.key]=v
    def read(self,p):return self.voltages.get(p.key,0.)

class PicoTests(unittest.TestCase):
    def make(self,source):
        p=Pico(source=source).attach(MockEmulator());self.addCleanup(p.close);return p
    def test_mapping(self):
        p=self.make('pass')
        self.assertEqual(len(p.board.pins),40)
        self.assertEqual(GPIO_PADS[26],'31')
        self.assertEqual(p.pin('VBUS').pad,'40')
        self.assertNotIn(25,GPIO_PADS)
        self.assertEqual(PAD_NAMES[32],'AGND')
    def test_write_sleep_adc(self):
        p=self.make('from machine import Pin, ADC\nimport time\np=Pin(0,Pin.OUT,value=1)\ntime.sleep_ms(10)\np.off()\na=ADC(26).read()\nu=ADC(26).read_u16()\nt=time.ticks_ms()')
        p.emu.voltages[p.pin(26).key]=1.65
        original=sys.modules.get('time')
        p.step_due(0)
        self.assertEqual(p.emu.read(p.pin(0)),3.3)
        self.assertFalse(p.done)
        p.step_due(.009)
        self.assertEqual(p.emu.read(p.pin(0)),3.3)
        p.step_due(.010)
        self.assertTrue(p.done)
        self.assertEqual(p.emu.read(p.pin(0)),0.)
        self.assertEqual(p.globals['a'],2048)
        self.assertEqual(p.globals['u'],32775)
        self.assertEqual(p.globals['t'],10)
        self.assertIs(sys.modules.get('time'),original)
    def test_irq_timer(self):
        p=self.make('from machine import Pin,Timer\nfrom time import sleep_ms\nevents=[]\np=Pin(1,Pin.IN)\np.irq(lambda pin:events.append("edge"))\nt=Timer()\nt.init(period=2,mode=Timer.ONE_SHOT,callback=lambda t:events.append("timer"))\nsleep_ms(5)\nsleep_ms(1)')
        p.step_due(0)
        p.emu.voltages[p.pin(1).key]=3.3
        p.step_due(.002)
        p.step_due(.005)
        p.step_due(.006)
        self.assertEqual(p.globals['events'],['edge','timer'])
    def test_bus_callback(self):
        p=self.make('from machine import I2C\nx=I2C(0).readfrom(72,2)')
        p.bus_handlers[('I2C',0)]=lambda method,*args:b'\x01\x02'
        p.step_due(0)
        self.assertEqual(p.globals['x'],b'\x01\x02')
    def test_missing_footprint(self):
        p=self.make('pass')
        with self.assertRaises(ValueError):Pico(board=p.board,ref='U_PICO')
    def test_pwm(self):
        p=self.make('from machine import Pin,PWM\nfrom time import sleep\nw=PWM(Pin(2),freq=10,duty_u16=32768)\nsleep(1)')
        p.step_due(0);p.step_due(.01)
        self.assertEqual(p.emu.read(p.pin(2)),3.3)
        p.step_due(.075)
        self.assertEqual(p.emu.read(p.pin(2)),0.)
    def test_error(self):
        p=self.make('raise ValueError("bad firmware")')
        with self.assertRaisesRegex(ValueError,'bad firmware'):p.step_due(0)

if __name__=='__main__':unittest.main()
