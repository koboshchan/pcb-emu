"""Off-board ADS1115 register-level ADC and Pico I2C transaction adapter.

Source: https://www.ti.com/lit/ds/symlink/ads1115.pdf, sections 7.3 and 8.
Ideal quantization, nominal 1/data_rate conversion periods, endpoint sampling.
No delta-sigma filter, noise, input loading, comparator/ALERT, oscillator error,
I2C wire timing, or input protection model. Inputs must remain within supplies;
PGA full-scale is NOT permission to exceed VDD. No PCB files are modified.
"""
import math
from .core import Board


class ADS1115:
    RANGES = (6.144, 4.096, 2.048, 1.024, .512, .256, .256, .256)
    RATES = (8, 16, 32, 64, 128, 250, 475, 860)
    ADDRESSES = {'GND': 0x48, 'VDD': 0x49, 'SDA': 0x4A, 'SCL': 0x4B}
    PINS = ('A0', 'A1', 'A2', 'A3', 'VDD', 'GND', 'SDA', 'SCL', 'ADDR')

    def __init__(self, name='ads1115', *, addr='GND'):
        if addr not in self.ADDRESSES:
            raise ValueError('ADDR must be tied to GND, VDD, SDA or SCL')
        self.addr = addr
        pads = {p: {'node': f'{name}:{p}', 'label': p} for p in self.PINS}
        self.board = Board(name=name, extracted={
            'nets': [{'node': p['node']} for p in pads.values()],
            'components': [{'ref': 'J_ADC', 'value': 'Virtual ADS1115',
                            'footprint': 'Virtual:ADS1115', 'pads': pads}]})
        self.emu = None
        self.gain_error=0.;self.offset_error=0.;self.inl_error=0.;self.noise_rms=0.;self.noise_seed=0
        self.reset()

    @property
    def address(self):
        return self.ADDRESSES[self.addr]

    def pin(self, name):
        return self.board.pin('J_ADC', name)

    def attach(self, emu):
        if self.emu is not None:
            raise ValueError('ADS1115 is already attached')
        emu.add_board(self.board)
        emu.connect(self.pin('ADDR'), self.pin(self.addr), resistance=0)
        self.emu = emu
        emu.peripherals.append(self)
        return self

    def reset(self):
        self.registers = [0, 0x8583, 0x8000, 0x7FFF]
        self.pointer = 0
        self.deadline = None
        self.active_config = None
        self.now = 0.

    def powered(self):
        if self.emu is None:
            return False
        supply = self.emu.read(self.pin('VDD')) - self.emu.read(self.pin('GND'))
        return 2. <= supply <= 5.5

    @property
    def conversion_time(self):
        return 1 / self.RATES[(self.registers[1] >> 5) & 7]

    def _start(self, now):
        self.active_config = self.registers[1]
        self.deadline = now + 1 / self.RATES[(self.active_config >> 5) & 7]

    def _sample(self):
        ground = self.emu.read(self.pin('GND'))
        supply = self.emu.read(self.pin('VDD')) - ground
        mux = (self.active_config >> 12) & 7
        positive, negative = ((0, 1), (0, 3), (1, 3), (2, 3),
                              (0, None), (1, None), (2, None), (3, None))[mux]
        def voltage(channel):
            if channel is None:
                return 0.
            value = self.emu.read(self.pin(f'A{channel}')) - ground
            if not math.isfinite(value) or not 0 <= value <= supply:
                raise ValueError('ADS1115 input outside GND..VDD; protection is not modeled')
            return value
        differential = voltage(positive) - voltage(negative)
        fs = self.RANGES[(self.active_config >> 9) & 7]
        ideal=differential*32768/fs
        # Explicit bounded sinusoidal INL assumption, not a measured code map.
        value=ideal*(1+self.gain_error)+self.offset_error+self.inl_error*math.sin(math.pi*ideal/32768)
        if self.noise_rms:
            import hashlib,random
            key=f'{self.noise_seed}:{self.board.name}:{float(self.now).hex()}:{self.active_config}'
            rng=random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],'big'))
            value+=rng.gauss(0,self.noise_rms)
        code = max(-32768, min(32767, round(value)))
        self.registers[0] = code & 0xFFFF

    def advance(self, now):
        """Complete due conversions using the current solved endpoint voltage.

        If a caller jumps across several periods, only the latest endpoint is
        sampled. Use emulator substeps for changing inputs; this is not a
        historical waveform integrator or the chip's delta-sigma filter.
        """
        if now < self.now:
            raise ValueError('ADS1115 simulated time cannot go backwards')
        self.now = float(now)
        if not self.powered():
            self.reset()
            self.now = float(now)
            return
        if self.deadline is None:
            return
        if now + 1e-12 < self.deadline:
            return
        completed = self.deadline
        self._sample()
        self.deadline = None
        # Config writes during a conversion take effect on the next one.
        if not self.registers[1] & 0x100:
            self._start(completed)
            if self.deadline <= now:
                period = 1 / self.RATES[(self.active_config >> 5) & 7]
                self._sample()
                self.deadline += (math.floor((now - self.deadline) / period) + 1) * period

    def _check(self, now):
        if not self.powered():
            self.reset()
            self.now = float(now)
            raise OSError('ADS1115 unpowered or supply outside 2..5.5 V')
        self.advance(now)

    def write(self, payload, now):
        self._check(now)
        payload = bytes(payload)
        if len(payload) not in (1, 3):
            raise ValueError('ADS1115 write needs pointer or pointer plus two bytes')
        pointer = payload[0]
        if pointer not in range(4):
            raise ValueError('ADS1115 register pointer must be 0..3')
        if len(payload) == 3:
            value = int.from_bytes(payload[1:], 'big')
            if pointer == 1:
                if value & 3 != 3:
                    raise NotImplementedError('ADS1115 comparator/ALERT is not modeled')
                self.registers[1] = value & 0x7FFF
                if self.deadline is None and (value & 0x8000 or not value & 0x100):
                    self._start(now)
            elif pointer != 0:
                self.registers[pointer] = value
            # Conversion register is read-only.
        self.pointer = pointer
        return len(payload)

    def read(self, n, now):
        self._check(now)
        if n not in (1, 2):
            raise ValueError('ADS1115 reads support one or two register bytes')
        value = self.registers[self.pointer]
        if self.pointer == 1:
            value = (value & 0x7FFF) | (0x8000 if self.deadline is None else 0)
        return value.to_bytes(2, 'big')[:n]


class ADS1115Bus:
    """Transaction-level callback for Pico.bus_handlers[('I2C', bus_id)]."""
    def __init__(self, devices, *, clock):
        self.devices = list(devices)
        addresses = [d.address for d in self.devices]
        if len(set(addresses)) != len(addresses):
            raise ValueError('Duplicate ADS1115 I2C addresses')
        self.clock = clock

    def __call__(self, method, *args):
        now = self.clock()
        if method == 'scan':
            return sorted(d.address for d in self.devices if d.powered())
        address = args[0]
        if address == 0 and method == 'writeto' and bytes(args[1]) == b'\x06':
            for device in self.devices:
                device.reset()
            return 1
        device = next((d for d in self.devices if d.address == address), None)
        if device is None:
            raise OSError(f'No ADS1115 at I2C address {address:#x}')
        if method == 'writeto':
            return device.write(args[1], now)
        if method == 'readfrom':
            return device.read(args[1], now)
        if method in ('writeto_mem', 'readfrom_mem'):
            _, pointer, data, addrsize = args
            if addrsize != 8:
                raise ValueError('ADS1115 requires an 8-bit register pointer')
            if not 0 <= pointer <= 3:
                raise ValueError('ADS1115 register pointer must be 0..3')
            if method == 'writeto_mem':
                device.write(bytes([pointer]) + bytes(data), now)
                return None
            device.write(bytes([pointer]), now)
            return device.read(data, now)
        raise NotImplementedError(f'ADS1115 I2C operation {method!r}')
