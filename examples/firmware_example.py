"""Example only. GP assignments require explicit external wiring.

This shifts 64 bits on GP0/1/2 and reads the three physical ADC inputs.
The motherboard has ten separate analog outputs, not an onboard ten-channel
ADC mux. To sample all ten, supply and wire an external multiplexer, then
provide select_external_channel(channel) in the firmware environment.
"""
from machine import Pin, ADC
from time import sleep_us, sleep_ms

data = Pin(0, Pin.OUT, value=0)
clock = Pin(1, Pin.OUT, value=0)
latch = Pin(2, Pin.OUT, value=0)
adcs = [ADC(26), ADC(27), ADC(28)]


def shift64(word):
    latch.off()
    for bit in range(63, -1, -1):
        clock.off()
        data.value((word >> bit) & 1)
        sleep_us(1)
        clock.on()
        sleep_us(1)
    clock.off()
    latch.on()
    sleep_us(1)
    latch.off()


shift64(0x0123456789ABCDEF)
sleep_ms(1)
readings = [adc.read_u16() for adc in adcs]
if 'select_external_channel' in globals():
    ten_channels = []
    for channel in range(10):
        select_external_channel(channel)
        sleep_us(10)
        ten_channels.append(adcs[0].read_u16())
