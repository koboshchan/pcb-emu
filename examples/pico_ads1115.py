"""One virtual Pico reads one ADS1115 through explicit I2C wiring."""
from pcb_emu import Emulator,ADS1115,ADS1115Bus

FIRMWARE='''from machine import Pin,I2C
from time import sleep_ms
bus=I2C(0,sda=Pin(0),scl=Pin(1))
bus.writeto_mem(0x48,1,b"\\xc3\\xe3")
sleep_ms(2)
reading=int.from_bytes(bus.readfrom_mem(0x48,0,2),'big')
'''


def attach_readout(emu,voltage=1.25):
    adc=ADS1115().attach(emu)
    pico=emu.add_pico(source=FIRMWARE)
    for terminal,pin in [('VDD','3V3'),('GND','GND'),('SDA','GP0'),('SCL','GP1')]:
        emu.connect(adc.pin(terminal),pico.pin(pin),resistance=0)
    for i in range(4):emu.drive(adc.pin(f'A{i}'),voltage if i==0 else 0)
    pico.bus_handlers[('I2C',0)]=ADS1115Bus([adc],clock=lambda:pico.now)
    emu.dc()
    return pico,adc


def main():
    e=Emulator();pico,adc=attach_readout(e)
    try:
        e.run(ticks=5)
        print('ADC code',pico.globals['reading'])
    finally:pico.close()

if __name__=='__main__':main()
