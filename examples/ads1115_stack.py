"""Explicit off-board ADS1115/Pico wiring; no board edits or added divider.

For a settled stack created by mnist_stack.build_stack(), call attach_readout,
then emu.run(ticks=50). The trusted firmware prints ten codes and argmax.
The existing board's division/protection remains the actual analog circuit.
"""
from pathlib import Path
from pcb_emu import ADS1115, ADS1115Bus


def attach_readout(emu, motherboard=None):
    mb = motherboard or emu.boards['MB']
    pico = emu.add_pico(code=Path(__file__).with_name('ads1115_firmware.py'))
    devices = []
    for index, addr in enumerate(('GND', 'VDD', 'SDA')):
        adc = ADS1115(name=f'ads{index}', addr=addr).attach(emu)
        for terminal, pico_pin in [('VDD', '3V3'), ('GND', 'GND'),
                                    ('SDA', 'GP0'), ('SCL', 'GP1')]:
            emu.connect(adc.pin(terminal), pico.pin(pico_pin))
        for channel in range(min(4, 10 - index * 4)):
            emu.connect(adc.pin(f'A{channel}'), mb.pin('JAD', str(index * 4 + channel + 1)))
        devices.append(adc)
    emu.connect(pico.pin('GND'), mb.pin('JAD', '11'))
    # High idle bus approximates pull-ups. Transactions are callback-level,
    # not electrical I2C edges, capacitance or clock stretching simulation.
    emu.drive(pico.pin('GP0'), 3.3)
    emu.drive(pico.pin('GP1'), 3.3)
    pico.bus_handlers[('I2C', 0)] = ADS1115Bus(devices, clock=lambda: pico.now)
    # New virtual terminals invalidate the node compilation. Settle supply and
    # signal wiring before the firmware's first bus transaction.
    emu.dc()
    return pico, devices
