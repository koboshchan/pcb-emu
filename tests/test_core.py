import unittest
import numpy as np
from pcb_emu.core import Board,Emulator
from pcb_emu.components import AHCT595,number

def circuit(parts):
    nets=set(n for _,_,pins in parts for n in pins.values())
    return Board(name='b',extracted={'board':'b','nets':[{'node':n,'pads':[],'labels':[]} for n in nets], 'components':[{'ref':ref,'value':value,'footprint':'test','pads':{p:{'node':n,'label':'','layers':[],'xy_mm':[0,0]} for p,n in pins.items()}} for ref,value,pins in parts]})

class SolverTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(number('0R'),0);self.assertEqual(number('4.7k'),4700);self.assertAlmostEqual(number('1uF'),1e-6)
    def test_divider(self):
        b=circuit([('R1','1k',{'1':'a','2':'b'}),('R2','1k',{'1':'b','2':'g'})]);e=Emulator();e.add_board(b);e.drive(b.pin('R1','1'),5);e.drive(b.pin('R2','2'),0);e.dc();self.assertAlmostEqual(e.read(b.pin('R1','2')),2.5,places=7)
    def test_callback_next_tick(self):
        b=circuit([('R1','1k',{'1':'a','2':'g'})]);e=Emulator(tick=.002);e.add_board(b);e.drive(b.pin('R1','1'),1);e.drive(b.pin('R1','2'),0);seen=[]
        def cb(now):seen.append((now.tick,now.time,now['b.R1.1']));e.drive(b.pin('R1','1'),2)
        e.run(2,cb);self.assertEqual(seen,[(1,.002,1.),(2,.004,2.)])
    def test_rc(self):
        b=circuit([('R1','1k',{'1':'a','2':'b'}),('C1','1uF',{'1':'b','2':'g'})]);e=Emulator();e.add_board(b);e.drive(b.pin('R1','1'),1);e.drive(b.pin('C1','2'),0);e.run(1);self.assertAlmostEqual(e.read(b.pin('C1','1')),.5,places=6)
    def test_diode(self):
        b=circuit([('R1','1k',{'1':'a','2':'b'}),('D1','1N4148W',{'2':'b','1':'g'})]);e=Emulator();e.add_board(b);e.drive(b.pin('R1','1'),5);e.drive(b.pin('D1','1'),0);e.dc();self.assertTrue(.5<e.read(b.pin('D1','2'))<.8)
    def test_opamp(self):
        pins={'1':'o','2':'o','3':'input','4':'pos','5':'g','6':'u','7':'u','8':'v','9':'v','10':'g','11':'neg','12':'g','13':'w','14':'w'}
        b=circuit([('U1','TL074',pins)]);e=Emulator();e.add_board(b)
        for p,v in [('3',1),('4',15),('5',0),('11',-15)]:e.drive(b.pin('U1',p),v)
        e.dc();self.assertAlmostEqual(e.read(b.pin('U1','1')),1,places=4)

if __name__=='__main__':unittest.main()
