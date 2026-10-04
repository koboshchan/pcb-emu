# Seeded variation

`Variation(...).apply(emu, seed)` samples a fresh physical unit. Add all boards, supplies and ADCs first, apply once, then drive and simulate. Repeated application is rejected rather than silently compounding tolerances. Samples are available in `emu.variation_sample`. Traversal is sorted by board name and reference. Changing board names or inserting parts can change random draws.

```python
from pcb_emu import Emulator, Variation
from circuits import divider
emu = Emulator()
b = emu.add_board(divider())
Variation(resistor_tolerance=.01, temperature=40).apply(emu, seed=42)
emu.drive(b.pin('R1', '1'), 5)
emu.drive(b.pin('R2', '2'), 0)
emu.dc()
print(emu.read(b.pin('R1', '2')))
```

Noise draws are keyed by seed and simulated endpoint time, frozen throughout each Newton solve. The same time yields the same noise. Substeps change the sampling times; this is not a continuous band-limited noise process. Specify `noise_bandwidth=0` and `supply_noise_rms=0` to disable analog random noise. ADS conversion noise is independently controlled by `adc_noise_rms`.

## Defaults and evidence

These are engineering scenario assumptions, not measured component distributions, correlated lot distributions or a manufacturing yield guarantee. Uniform bounds are deliberately not claimed to be Gaussian datasheet standard deviations. Analog devices and operating conditions must be selected by the caller.

| Parameter | Default | Evidence or assumption |
| --- | --- | --- |
| Resistor tolerance | uniform ±1% | Assumption; actual purchased resistor grades required |
| Capacitor tolerance | uniform ±10% | Assumption; no DC accuracy effect in a settled circuit |
| Resistor temperature coefficient | +100 ppm/°C | Assumption, not a guaranteed purchased-part value |
| Ambient temperature | 25°C | Caller-selected constant; no self-heating solver |
| TL074 per-channel offset | uniform ±6 mV | TI TL074 maximum at 25°C; uniform distribution assumed |
| TL074 offset drift | uniform ±18 µV/°C | TI typical magnitude; signed distribution assumed, not a max bound |
| TL074 bias current | uniform ±200 pA at 25°C | TI max magnitude; direction and doubling each 10°C assumed |
| TL074 open-loop gain | nominal 100000, uniform ±20% | Behavioral baseline and spread assumptions, not datasheet yield |
| TL074 GBW | nominal 3 MHz, uniform ±20% | TI nominal; spread assumption |
| TL074 slew rate | nominal 13 V/µs, uniform ±20% | TI nominal; spread assumption |
| TL074 input noise | 37 nV/√Hz, default 1 kHz bandwidth | TI typical at 1 kHz; white approximation ignores 1/f noise |
| Diode forward shift | uniform ±30 mV | Assumed process spread |
| Diode temperature shift | −2 mV/°C | Assumed silicon coefficient; Is temperature behavior not modeled |
| L7805 output tolerance | uniform ±4% | Conservative scenario assumption, not manufacturer/grade-specific |
| External PSU voltage tolerance | uniform ±1% | Assumption; applies only to explicit PowerSupply objects |
| PSU ripple | 10 mV peak at channel frequency | Assumption, sinusoidal; applies only to explicit supplies |
| PSU noise | 1 mV RMS | Assumed endpoint Gaussian sample |
| Resistor Johnson noise | sqrt(4 k T bandwidth / R) A RMS | Thermal current noise formula, ideal white endpoint approximation |
| ADS1115 gain error | uniform ±0.15% | TI max at ±2.048V, 25°C; applying to other PGA settings is an assumption |
| ADS1115 offset error | uniform ±3 LSB | TI magnitude at ±2.048V; other PGA/rate settings approximate |
| ADS1115 INL | bounded ±1 LSB sinusoid | TI 8 SPS, ±2.048V magnitude; sinusoidal shape assumed |
| ADS1115 conversion noise | 0.5 LSB RMS | Scenario assumption, not claimed as a guaranteed datasheet value |

Sources checked are [TI TL074 product specifications](https://www.ti.com/product/TL074), [TI TL07xx datasheet](https://www.ti.com/lit/ds/symlink/tl074.pdf) and [TI ADS1115 datasheet](https://www.ti.com/lit/ds/symlink/ads1115.pdf). TL074 defaults are the older TL07x family, not the TL07xH upgrade. Specs at ±15V and the stated load/temperature must not be generalized to every supply and common-mode range. ADS errors depend on PGA, rate, supply and temperature.

## Implementation and limits

TL074 offset and bias are stamped into KCL. A dominant-pole backward-Euler approximation uses GBW and gain in transient mode, followed by smooth rail clipping and a slew limit. It is not a validated multi-pole op-amp macromodel. DC ignores GBW/slew. The output impedance is a fixed behavioral 50 ohms. There is no input common-mode phase reversal, overload recovery, realistic quiescent supply current, output-current protection or full PSRR model.

Diode thermal voltage scales with absolute temperature; a horizontal forward-voltage shift approximates spread/drift. This preserves a continuous value and derivative at the exponential/linear extension boundary. It does not capture leakage temperature dependence or recovery charge.

Regulator variation applies to the regulated branch of the simple dropout model. PSU tolerance/ripple/noise affect explicit supply channels, not arbitrary `drive` functions. Application code that uses ideal driven rails must vary those sources itself. Ideal GPIO/PWM average sources must also be varied explicitly if supply dependence is wanted.

Capacitor tolerance changes transient coefficients only. Copper resistance uses the emulator's ambient temperature when its graph is compiled. ADC gain/offset/INL/noise are applied before quantization and saturation in the actual ADS1115 peripheral model. This does not add switched-capacitor loading, comparator behavior, delta-sigma filtering or electrical bus edges.

Settled DC Monte Carlo can cover resistor/offset/bias/diode/regulator/supply drift and endpoint noise. It cannot establish full PWM/transient settling, capacitor sensitivity, GBW/slew sensitivity, EMC immunity or physical hardware accuracy. Report convergence failures separately and count them as incorrect for conservative application accuracy.
