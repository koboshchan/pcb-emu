# pcb-emu

A Python library that extracts physical copper connectivity from KiCad PCB files and simulates component models. Distribution `pcb-emu`, import `pcb_emu`. No schematics, training weights, design netlists or SPICE are used.

This is an early implementation, not a validated substitute for bench measurements. Small-circuit tests pass. Full-stack MNIST accuracy, GPU nonlinear batch solving and detailed transient silicon behavior are still under validation. Do not use it as a fabrication sign-off.

## Install

Use Python 3.11+ with NumPy, SciPy and Shapely. PCB extraction also needs the `pcbnew` module installed with KiCad. The `[kicad]` extra documents this dependency but cannot install KiCad from PyPI. On Linux, run with the system interpreter if KiCad uses system Python. `PYTHONNOUSERSITE=1` avoids conflicting user-site NumPy builds.

```sh
python -m pip install -e '.[test]'
python -m pytest
```

## API

```python
from pcb_emu import Emulator

emu = Emulator(tick=1e-3, ideal_copper=True)
mb = emu.add_board('motherboard.kicad_pcb', name='mb')
dc0 = emu.add_board('DC0_routed.kicad_pcb', name='dc0')
emu.plug(dc0, 'J0', mb, 'JD0')  # same pad numbers, or pass mapping={...}
emu.connect(dc0.pin('J0', '1'), mb.pin('JD0', '1'))
emu.add_jumper(mb.pin('JS1', 'B7'), mb.pin('JS2', 'B7'))
emu.drive(mb.pin('JP', '1'), 15)
emu.drive(mb.pin('JP', '2'), 0)
emu.drive(mb.pin('JP', '3'), -15)

def callback(now):
    print(now.tick, now.time, now.pin(mb, 'JS1', 'B7'))
    print(now['mb.JS1.B7'])
    # Iterate all pin names with `for key in now`.
    # Drives issued here become active on the NEXT tick.
    emu.drive(mb.pin('JSPI', '3'), 3.3 if now.tick % 2 else 0)

emu.run(ticks=100, callback=callback, substeps=10)
```

Pin names above are examples, not a hardcoded library pinout. A board loads one `.kicad_pcb` and never inserts a jumper or connects a daughterboard automatically. `Board.run()` provides a standalone board convenience runner; use an `Emulator` to attach supplies and signals.

The callback runs exactly once per tick. The default tick is 1 ms and is programmable. Smaller internal substeps do not increase callback frequency. Snapshot values use one immutable NumPy voltage array per tick and a shared pin-to-node index map, not copied dictionaries for every pin.

For faster edges, `emu.drive(pin, lambda t: ...)` evaluates a precomputed waveform at each internal substep. Choose substeps that resolve every edge; an undersampled waveform is not reconstructed automatically. The MNIST example contains a `ShiftRegisterStream` helper. Simulation is not cycle-accurate RP2040 execution.

## Models and solver

Each component has a class. Currently supported PCB values include resistors, capacitors, 1N4148W, TL074, 74AHCT595 and L7805. Unsupported electrical parts fail explicitly. The AHCT595 models serial shifting, latch clocks, reset, serial cascade output and output enable. Digital ICs sample the same old-state voltage snapshot, preventing chain order from shifting multiple stages in one event.

The solver stamps its own nodal equations, solves them with SciPy sparse linear algebra, linearizes diodes, and uses backward Euler for capacitors. An analytic Jacobian, residual-tested line search and finite-gain continuation stabilize nonlinear solving. Op amps have smooth rail clipping and a behavioral 50 Ω output resistance. These are simplified behavioral models without input bias/noise, realistic output current limiting, slew rate or dominant-pole dynamics. Full-stack ideal-copper DC solving converges for most tested images; 14 of the first 1000 test cases failed. Failed solves raise `ConvergenceError`, not a guessed voltage.

`emu.dc()` finds a static solution. `emu.run()` updates capacitor histories and digital state. Zero-ohm resistors currently use a small numerical resistance. Node-to-ground leakage is 1 pS for floating-node regularization.

## Copper

Connectivity is derived from intersections of pads, tracks, vias and zones refilled **in memory**. KiCad net labels are diagnostic only and never connect disconnected conductors. PTH pads/vias connect layers; opposed SMD pads do not. Source file SHA256 is checked before and after extraction, and PCB files are never saved.

`ideal_copper=True` uses geometrically connected ideal nodes for speed. `ideal_copper=False` builds a distributed resistor graph between pad terminals, track endpoints and intersection points. Trace resistance uses copper resistivity, segment length, width and thickness. Default copper is 35 µm; thickness and plating are model assumptions, not yet read from stackup. Vias use a plated-cylinder estimate. Planes use a star spreading-resistance approximation, not a meshed field solution. Connector contact and wire resistance default to 20 mΩ and 12 mΩ, configurable in the constructor or connection methods. Pads are treated as ideal metal islands.

The geometry module inventories approximate trace/via/plane capacitance and partial inductance. These C/L estimates are **not yet stamped into transient equations**. Do not mistake that inventory for a distributed RLC solver. Transmission lines, skin effect, return-path coupling and thermal solving are not implemented.

## Bench supply

```python
psu = emu.add_psu(channels={'+15': 15, '-15': -15}, current_limit=1.0)
emu.connect(psu.pin('+15+'), mb.pin('JP', '1'))
emu.connect(psu.pin('+15-'), mb.pin('JP', '2'))
emu.connect(psu.pin('-15+'), mb.pin('JP', '3'))
emu.connect(psu.pin('-15-'), mb.pin('JP', '2'))
psu.on()
# Read current, power, CV/CC mode in psu.channels[channel] after solving.
```

This is a behavioral source with configurable series resistance, voltage ripple and current limit. Current-limit transitions and supply startup are not fully validated. The supply does not model op-amp/logic quiescent current that the simplified IC classes do not consume.

## Examples and input provenance

`examples/mnist_stack.py` assembles the eight-board neural stack from caller-provided paths and inserts its approved wire explicitly. No PCB files or MNIST files are vendored. Its pixel mapping is an assumption, exact area averaging from 28×28 to 8×8, row-major, 6-bit quantization, white pixel equals higher duty cycle. Averaged PWM is applied at the actual 595 Q pins and then passes through extracted RC and resistor connectivity. It is not firmware timing or a trained weight matrix.

## Security

PCB parsing and user firmware should only use trusted files. The CPython firmware runner executes actual Python with process permissions; it is not a sandbox. Never run untrusted firmware on a host containing secrets.

## Pico firmware

```python
pico = emu.add_pico(code='main.py')
emu.connect(pico.pin('GP0'), mb.pin('JSPI', '3'))
emu.connect(pico.pin('GP1'), mb.pin('JSPI', '4'))
emu.connect(pico.pin('GP2'), mb.pin('JSPI', '5'))
emu.connect(pico.pin('GP26'), mb.pin('JAD', '1'))
emu.run(ticks=100)
pico.close()
```

The virtual Pico exposes the real 40-pin header, GP0–GP22 and GP26–GP28, plus GND, AGND, RUN, ADC_VREF, 3V3, 3V3_EN, VSYS and VBUS. GP23–25 are not exposed on the header. To attach to a PCB footprint instead, pass `board=...` and `ref=...`; the footprint must actually have pads 1–40. The neural PCB has no Pico footprint, so use the off-board virtual header.

Firmware is CPython executing trusted MicroPython-style source. Fake `machine`, `time`/`utime` and `rp2` imports are local to the runner. Pin operations and sleeps rendezvous with simulated time; bitbang pin transitions settle individually. CPU-only loops without pin operations or sleep cannot be preempted and produce a watchdog error. This is neither cycle-accurate RP2040 hardware nor a MicroPython VM. There is no substantive PIO emulation.

Pin IRQs, PWM, ADC, SPI, I2C, UART and Timer interfaces are present. ADC returns 12-bit or scaled `read_u16` values. Buses require explicit attached callbacks, rather than invented devices. PWM is sampled digital voltage at simulation service times; choose sufficient timing granularity. Power pins get explicit ideal defaults and do not implement Pico power-regulator dynamics. `examples/firmware_example.py` shifts 64 serial bits and reads the three available ADC pins. The PCB has ten separate analog output wires and no mux; reading all ten from one Pico needs added off-board hardware or explicit rewiring.

`ADS1115` and `ADS1115Bus` provide an explicit off-board solution. `examples/ads1115_stack.py` adds three virtual ADC modules with ADDR tied to GND, VDD and SDA for addresses 0x48, 0x49 and 0x4A. All use 3.3 V and common ground, GP0 SDA and GP1 SCL. JAD pins 1–4 connect to the first module's A0–A3, pins 5–8 to the second, and pins 9–10 to the third's A0–A1. JAD 11 and 12 are ground. The existing motherboard divider/clamps are retained, not replaced or duplicated. Real modules need I2C pull-ups to 3.3 V. No PCB files or footprints are changed.

`examples/ads1115_firmware.py` reads all ten single-ended scores through normal MicroPython I2C register transactions, polls OS readiness, and prints their argmax. It selects the same ±4.096 V PGA on every channel, 860 samples/s and single-shot mode. Conversion values are held until nominal 1/data-rate time has elapsed. Register pointers, big-endian signed codes, MUX and all PGA/rate settings are modeled. Comparator/ALERT requests raise an explicit unsupported error. Supply loss resets registers; selected inputs outside GND..VDD raise an error rather than pretending the PGA or existing diode makes overvoltage safe.

The ADC has ideal input impedance and quantization. It does not model switched-capacitor loading, delta-sigma integration, noise, oscillator error, ALERT or electrical I2C edges. Conversions sample the solved voltage at completion; skipped continuous periods use the current endpoint, not historical waveform integration. ADCs advance after solver substeps. Firmware remains trusted full-privilege CPython, not a sandbox.

For the actual extracted PCB stack, run `PYTHONPATH=src:examples python examples/ads1115_demo.py --extracted runs/extracted_geometry.json --images data/t10k-images-idx3-ubyte.gz --index 2 --out runs/ads1115_readout.json`. This validates source hashes before and after the run. The completed test read ten physical JAD voltages through three ADCs and Pico firmware, predicting 1, matching the nominal analog prediction. JAD voltages ranged from 1.28765 V to 1.83826 V. This is one held averaged-PWM input with capacitors initialized at their solved operating point, not a new 1000-image accuracy result or hardware validation.

## Batch linear algebra and CUDA

```python
from pcb_emu.backend import ArrayBackend

backend = ArrayBackend('auto')
factor = backend.factor(A)  # A is float64 N×N
voltages = factor.solve(B)  # B has shape batch×N
```

The backend supports NumPy/SciPy, PyTorch CPU/CUDA and CuPy CUDA. Explicit CUDA requests fail if unavailable rather than silently falling back. `auto` tries functioning CUDA installations. The `[gpu]` extra includes Torch and CuPy for CUDA 12; for other CUDA environments install the appropriate optional library manually. Reuse a factorization for repeated shared-matrix right-hand sides.

Run `python -m pcb_emu.backend --n 400 --batch 1000` for synthetic float64 timings and residual checks. A real RTX 4070 SUPER test measured 1.39× faster cached 1000-RHS solves than CPU with residual below 1e-15. This measures linear algebra, not end-to-end neural PCB classification. The nonlinear emulator presently uses the CPU sparse solver one state at a time. Vectorized nonlinear batches, GPU PWM simulation and Monte Carlo orchestration are not yet integrated.
