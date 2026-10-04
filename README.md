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

The solver stamps its own nodal equations, solves them with SciPy sparse linear algebra, linearizes diodes, and uses backward Euler for capacitors. Op amps use finite gain and smooth rail clipping. These are simplified behavioral models without input bias/noise, realistic output current limiting, slew rate or dominant-pole dynamics. DC convergence of the entire neural PCB is not yet established; failures raise `ConvergenceError`, not a guessed voltage.

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

PCB parsing and user firmware should only use trusted files. Any forthcoming CPython firmware runner executes actual Python with process permissions; it is not a sandbox. Never run untrusted firmware on a host containing secrets.
