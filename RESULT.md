# Validation result

## Scope

This is a PCB-only simulation result, not a measurement and not a fabrication approval. Only `.kicad_pcb` copper, pad geometry, embedded component values and generic named-part behavioral models were used. No schematics, design netlists, weights JSON, training code or reference accuracy scripts were read. The approved IN_38 wire is inserted explicitly by the stack example. No source board was modified.

## MNIST

The first 1000 official MNIST test images produced **633 correct classifications, 63.3%**. Fourteen nonlinear solver failures count as incorrect, not excluded. Runtime was 436.218 seconds. Classification is argmax of the ten actual JAD ADC connector voltages. Every solved sample stayed within 0–3.3 V at these pins.

This run uses ideal within-board copper, finite 20 mΩ connector contacts, the explicit 12 mΩ jumper, averaged PWM at the physical 595 output pins, actual resistor/capacitor connectivity, simplified finite-gain TL074 models with 50 Ω output resistance, and a CPU nonlinear nodal solver. Pixels are exact area-averaged from 28×28 to 8×8, row-major, six-bit quantized, no inversion. This mapping is a declared input assumption, not recovered firmware.

Correct predictions per true digit 0–9 were `[78,124,100,58,110,70,21,24,48,0]`. Digit 9 had no correct predictions and usually became 4. Digits 6 and 7 also performed poorly. These results do not identify whether the cause is hardware weights/topology, pixel orientation/preprocessing, or limitations in the component models. They must not be presented as measured physical-board accuracy.

Solver failures occurred at indices `[0,1,83,291,391,414,415,441,462,463,540,788,925,979]`. A failed solve is reported, not converted to invented voltages.

Local full sample report is `runs/mnist1000_contacts.json`. `examples/summarize_accuracy.py` prints its confusion matrix. The earlier `runs/mnist1000.json` was started before retaining finite connector resistance and is superseded; do not use it as the final result.

To reproduce:

```sh
PYTHONNOUSERSITE=1 PYTHONPATH=src:examples OPENBLAS_NUM_THREADS=1 /usr/bin/python3 examples/mnist_accuracy.py \
  --pcb-root /path/to/pcbai \
  --images /path/to/t10k-images-idx3-ubyte.gz \
  --labels /path/to/t10k-labels-idx1-ubyte.gz \
  --count 1000 --out runs/mnist1000_contacts.json
```

The MNIST IDX files were downloaded from the public fgnt/mnist mirror. No dataset or PCB is vendored in this repository.

## Distributed copper limitation

A freshly extracted distributed copper graph compiled **56,968 nodes**. Its blank-input nonlinear solve failed the dual convergence criterion at gain scale 0.0001, with scaled residual `3.56478e-14` but no accepted sufficiently small voltage step. Therefore full-stack nonideal copper operation is **not validated**. Small geometry tests and a supply-driven trace test pass, but that does not establish full-board parasitic accuracy.

Trace/via/plane C and L are inventory estimates only, not stamped into transient equations. There is no transmission-line, mutual-inductance, field-solver, skin-effect or return-path model. Default copper thickness is 35 µm and plating is 25 µm unless overridden; stackup thickness is read, copper layer thickness is currently a stated default. Zone resistance uses an approximate star network.

## PWM filter check

An isolated actual DC0 `RP0=10 kΩ`, `CP0=1 µF` filter was selected from physical pads and embedded values. A 5 V waveform at 1 kHz, duty `31/63`, was integrated by backward Euler with 126 steps per period for 150 periods. The last-period mean was **2.460315020 V**, expected **2.460317460 V**, error **−2.44 µV**. Ripple ranged from **2.397885173 V** to **2.522778004 V**.

This validates that isolated RC integration converges to the expected average. It is not full-stack PWM, shift-register timing, finite op-amp bandwidth or downstream loading validation. Local trace output is `runs/pwm_rc.json`.

## CPU and GPU benchmark

A real read-only RTX 4070 SUPER test used float64, a 400×400 dense matrix and 1000 shared-matrix RHS. Median cached solve was **6.049 ms CPU**, **4.341 ms Torch CUDA**, **1.393× speedup**. GPU relative residual was `9.97e-16`; relative difference to CPU was `7.33e-16`.

This is a linear shared-factor benchmark only. The nonlinear circuit/classification loop runs on CPU and is not GPU-vectorized. Local raw timing report is `runs/gpu_benchmark.json`.

## Seeded tolerance check

Ten seeded ±1% uniform component-value variations on test image 0 all failed nonlinear convergence. This does not produce a valid tolerance accuracy estimate. Image 0 also failed in the nominal 1000-image test, so this specific check cannot distinguish tolerance sensitivity from the existing solver failure. The failures are recorded in `runs/tolerance.json`; none were assigned fabricated predictions.

## Tests and package

37 tests pass; two accelerator-only tests skip on this host. Tests cover physical copper versus labels, opposite-layer SMD separation, vias, divider, diode, op-amp follower, RC, snapshot immutability, substep waveforms, next-tick callback drives, digital cascade timing, PSU CV/CC, trusted firmware execution, geometry resistance and backend multiple-RHS solves. A local wheel builds and imports. No PyPI upload or publishing workflow was created or run.

The Pico runner executes trusted full-privilege CPython, not a sandbox or RP2040/MicroPython VM. PIO is not emulated. Buses require explicitly attached device callbacks. The real Pico header has three external ADC channels; the neural board has ten outputs and no mux. Firmware cannot silently invent that missing hardware.

## Board provenance

All source SHA256 hashes were checked against extracted data and verified unchanged after testing.

| Board | SHA256 |
|---|---|
| Final post-CRB motherboard | `2d9c31c29f547419fe03c09b5cdac557ec5b5b10c9daffc802865c56e55777fa` |
| DC0 | `1196b0d47c1c553b22a4061d3ac7e1c41cbf3d4a35dd5b7f1d4cda102bfdb34a` |
| DC1a | `2954d17724d1cfd290225ee60bec2bfb9f9382dad0b09c4303918d32bb40375b` |
| DC1b | `3b720c292a842a584e030a6b8fb21fb373600280836980374d3699b85cc24151` |
| DC1c | `3fb7a7a89070453b1c1c8a219a7379496183ca8dac2b594b74c5bef4cf45aa4a` |
| DC1d | `bfd4a7115bb734fb9704616ec69f11c57c2a2fcd538f8d11849a982725b841d7` |
| DC2 | `f1fedb2c5fdc6529010a41f2048c27bb490a33e6c16147e1d7a03c1b4060bc15` |
| DC3 | `fc5b97c1068092910be16ea4e342ae0c0c8524affe952ab55fb664f5fcde4a1e` |

Additional off-board readout test used three ADS1115 modules at 0x48/0x49/0x4A, virtual Pico GP0/GP1 I2C, and ten actual JAD wires. Trusted firmware read image index 2 using single-shot conversions, ±4.096 V PGA and 860 samples/s. Codes were `[10301,14706,11596,11355,12794,11496,11563,12045,11455,11420]`; Pico argmax was 1, matching nominal analog argmax. All eight source hashes were checked before and after. Local raw report is `runs/ads1115_readout.json`. The suite now passes 70 tests with 2 GPU skips.

This additional test does not replace the 1000-image result. It uses averaged-PWM input and capacitor history initialized at the DC solution. ADC sampling is ideal endpoint quantization with no input loading, delta-sigma filter or electrical I2C timing. No source boards were changed, and no extra divider was inserted. The existing diode clamp is not a guarantee against overvoltage; this ADC model rejects selected input voltages outside its supply rails.

