"""Trusted Pico MicroPython firmware, three ADS1115s, ten JAD scores.

All ADS1115 modules powered at 3.3 V, common ground. SDA=GP0, SCL=GP1.
ADDR ties GND/VDD/SDA give addresses 0x48/0x49/0x4A respectively.
JAD pins 1..4 to first A0..A3, 5..8 to second, 9..10 to third A0..A1.
Leave third A2/A3 unused. Existing motherboard divider/clamps are retained.
Use external I2C pull-ups to 3.3 V, never 5 V. No PCB changes.
"""
from machine import I2C, Pin
from time import sleep_ms, ticks_ms, ticks_diff

bus = I2C(0, sda=Pin(0), scl=Pin(1), freq=400_000)


def read_score(address, channel):
    # OS=start, single-ended channel, PGA +/-4.096 V, single-shot,
    # 860 samples/s, comparator disabled. Same PGA on all scores.
    config = 0x8000 | ((4 + channel) << 12) | (1 << 9) | 0x100 | (7 << 5) | 3
    bus.writeto_mem(address, 1, config.to_bytes(2, 'big'))
    started = ticks_ms()
    while not int.from_bytes(bus.readfrom_mem(address, 1, 2), 'big') & 0x8000:
        if ticks_diff(ticks_ms(), started) > 100:
            raise RuntimeError('ADS1115 conversion timeout')
        sleep_ms(1)
    raw = int.from_bytes(bus.readfrom_mem(address, 0, 2), 'big')
    return raw - 65536 if raw & 0x8000 else raw


scores = [read_score(0x48 + i // 4, i % 4) for i in range(10)]
prediction = max(range(10), key=lambda i: scores[i])
print('ADS1115 scores', scores, 'prediction', prediction)
