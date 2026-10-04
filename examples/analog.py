"""Run divider, noninverting amplifier and PWM-filter demonstrations."""
from pcb_emu import Emulator
from circuits import divider,amplifier,rc


def main():
    b=divider();e=Emulator();e.add_board(b)
    e.drive(b.pin('R1','1'),5);e.drive(b.pin('R2','2'),0);e.dc()
    print('Divider output',e.read(b.pin('R1','2')))
    b=amplifier();e=Emulator();e.add_board(b)
    for pad,v in [('3',1),('4',15),('11',-15),('5',0)]:e.drive(b.pin('U1',pad),v)
    e.dc();print('Amplifier output',e.read(b.pin('U1','1')))
    b=rc();e=Emulator(tick=1e-4);e.add_board(b)
    e.drive(b.pin('C1','2'),0)
    e.drive(b.pin('R1','1'),lambda t:5. if t%1e-3<.25e-3 else 0.)
    e.run(ticks=1000,substeps=10)
    print('PWM filter endpoint',e.read(b.pin('C1','1')))

if __name__=='__main__':main()
