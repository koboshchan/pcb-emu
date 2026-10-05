# pcb-emu

Reusable Python PCB circuit simulation, with physical KiCad copper extraction and explicit component models. Distribution `pcb-emu`, import `pcb_emu`. No SPICE dependency. This is an early behavioral emulator, not manufacturer silicon simulation or fabrication sign-off.

## Install

Python 3.11+, NumPy, SciPy and Shapely are required. KiCad's matching `pcbnew` Python module is needed only to load PCB files. Install KiCad separately; it is not a PyPI extra. Use the interpreter supplied with your KiCad installation when extracting boards.

```sh
python -m pip install -e '.[test]'
python -m pytest
```

## Boards, wiring and simulation

```python
from pcb_emu import Emulator

emu = Emulator(tick=1e-4)
board = emu.add_board('divider.kicad_pcb', name='sensor')
emu.drive(board.pin('R1', '1'), 5)
emu.drive(board.pin('R2', '2'), 0)
emu.dc()
print(emu.read(board.pin('R1', '2')))

def callback(snapshot):
    print(snapshot.tick, snapshot.time, snapshot.pin(board, 'R1', '2'))
    # Drives issued in a callback become active on the next tick.
    emu.drive(board.pin('R1', '1'), 3.3)

emu.run(ticks=100, callback=callback, substeps=10)
```

`Board(path, name)` loads one PCB. `Board(name=..., extracted=...)` accepts caller-supplied virtual circuit metadata. `examples/circuits.py` demonstrates that schema without requiring KiCad. PCB labels are diagnostic, not wires. No daughterboards, sources or jumpers are inserted automatically.

`emu.connect(pin_a, pin_b, resistance=...)` joins any two terminals. `emu.add_jumper(...)` uses the configurable jumper resistance. `emu.plug(board_a, header_ref, board_b, socket_ref, mapping=...)` connects complete connector maps, defaulting to matching pad numbers. Connections persist and recompile the node graph. `drive` accepts a voltage or function of simulated time. Pins can be `Pin` objects or `board.reference.pad` strings. `dc` finds an operating point; `run` advances capacitor and digital state. `Board.run()` is a convenience for a standalone board.

Snapshots share an immutable voltage array and pin index map. Callback frequency is once per tick regardless of substeps. Resolve waveform edges through sufficient substeps. Firmware execution is not cycle-accurate hardware emulation.

## Generic examples

`examples/analog.py` runs a resistor divider, noninverting amplifier and RC PWM filter. `examples/pico_ads1115.py` explicitly wires one Pico and one ADS1115 and reads a known analog voltage through trusted MicroPython-style firmware. Run them with `PYTHONPATH=src:examples python examples/analog.py` or `PYTHONPATH=src:examples python examples/pico_ads1115.py`.

## Models and numerical limitations

Supported components are resistors, capacitors, 1N4148W diodes, TL074 quad op amps, 74AHCT595 shift registers and L7805 regulators. Unknown electrical parts fail explicitly. Connector names and analog net labels carry no device-specific behavior.

The custom nodal solver uses SciPy sparse linear algebra, analytic diode/op-amp Jacobians, residual-tested line search and gain continuation. Capacitors use backward Euler. TL074 defaults have finite gain, smooth rail clipping and 50-ohm behavioral output resistance. These are approximations, not a validated transistor model. Convergence failures raise `ConvergenceError`; floating nodes receive 1 pS leakage. Zero-ohm resistors use a small numerical resistance.

AHCT595 implements serial shift, cascade, reset, output enable and latch. Digital ICs sample a shared old-state snapshot, so chain order cannot cause multiple shifts in one event. L7805 is a simplified dropout/regulated-voltage model.

## Copper and parasitics

Extraction intersects pads, tracks, vias and zones refilled in memory. Source files are SHA256 checked and never saved. Opposed SMD pads do not connect; through-hole pads and vias connect layers.

`ideal_copper=True` merges actual connected copper into ideal nodes, preserving finite connector/wire resistances. `ideal_copper=False` builds a distributed resistor graph. Exact copper-contact overlaps are merged before solving, while finite trace, via and connector resistances remain. Via barrels have a separate tap on each traversed copper layer, including blind/buried spans. Saved KiCad stackup thicknesses set copper layer depths and per-layer copper thickness; otherwise layers are uniformly spaced across the board thickness and copper defaults to 35 micrometers. Via plating and plane spreading are assumptions. Planes use star spreading resistance, not a field mesh. Connector contact and jumper defaults are 20 and 12 milliohms. Temperature affects copper resistivity. DNP/DNI/DNF values and KiCad DNP flags leave the physical pads present but omit the electrical component stamp.

Approximate trace/via capacitance and inductance inventories are not stamped into transient equations. Distributed RLC, transmission lines, skin effect, return-path coupling and thermal solving are not implemented.

## Supply, Pico and ADC

`emu.add_psu({'channel': 5}, current_limit=1, output_resistance=.01, ripple=0)` creates explicit `channel+`/`channel-` pins. Wire them, ground a return and call `psu.on()`. Channel dictionaries expose current, power and CV/CC mode. Ripple is sinusoidal. Simplified ICs do not consume realistic supply current.

`emu.add_pico(code='main.py')` or `source='...'` creates the real 40-pin Pico header. GP23–25 are not exposed. Alternatively pass an existing PCB footprint through `board` and `ref`. Trusted CPython executes MicroPython-style `machine`, `time`/`utime` and `rp2` APIs. Pin operations and sleeps rendezvous with simulation time. Watchdogs detect noncooperating loops. IRQ, PWM, ADC, SPI, I2C, UART and Timer interfaces are available. Buses require caller-installed callbacks in `pico.bus_handlers`; no device is invented. There is no substantial PIO implementation or RP2040 instruction simulation. Close the Pico after use.

`ADS1115(name=..., addr='GND').attach(emu)` provides A0–A3, VDD, GND, SDA, SCL and ADDR terminals. Addresses are selected by GND/VDD/SDA/SCL straps. `ADS1115Bus` bridges explicit Pico I2C transactions. Registers implement signed big-endian codes, MUX, PGA, nominal conversion periods and readiness. Comparator/ALERT requests fail explicitly. Inputs must remain within GND..VDD even when PGA full scale exceeds VDD.

ADC defaults use ideal input impedance, endpoint sampling and quantization, not switched-capacitor loading or delta-sigma history. Skipped continuous conversion periods sample current endpoint voltage. Electrical I2C edges, oscillator error and pull-up loading are absent.

## Seeded variations

`Variation(...).apply(emu, seed)` samples resistor/capacitor tolerances, TL074 offsets/bias/gain/GBW/slew, diode shift, regulator error, ambient effects and ADS1115 errors. Noise is frozen during each solve and deterministic at a given time. Use fresh boards for each physical sample. Run `PYTHONPATH=src:examples python examples/variation.py --samples 100` for a seeded divider Monte Carlo. See [VARIATION.md](VARIATION.md) for distributions, datasheet sources and the substantial behavioral assumptions. DC does not measure capacitor, bandwidth or slew sensitivity.

## CPU linear algebra

The simulator uses NumPy and SciPy CPU algebra. `pcb_emu.backend.ArrayBackend()` also supports reusable LU factors with multiple right-hand sides for callers that already have a linear matrix.

## Security

PCB files and firmware must be trusted. The CPython firmware runner is not a sandbox and executes with host permissions. Never execute untrusted code on a machine containing secrets. This project is distributed through GitHub; no automated package publication is configured.
