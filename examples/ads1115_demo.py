"""Run trusted Pico firmware against ten actual solved PCB JAD outputs.

Uses averaged-PWM DC inputs, not full serial PWM silicon timing. ADS1115
samples endpoint voltages and uses ideal quantization; this is no measurement.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
from mnist_stack import build_stack, classify
from ads1115_stack import attach_readout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extracted', type=Path, required=True)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--index', type=int, default=2)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    extracted = json.loads(args.extracted.read_text())
    def check_sources():
        for board in extracted['boards']:
            digest = hashlib.sha256(Path(board['path']).read_bytes()).hexdigest()
            if digest != board['sha256']:
                raise ValueError(f"Source board changed: {board['board']}")
    check_sources()
    data = gzip.decompress(args.images.read_bytes())
    images = np.frombuffer(data[16:], dtype=np.uint8).reshape(-1, 28, 28)
    emu = build_stack(extracted=extracted)
    nominal = classify(emu, images[args.index])
    pico, devices = attach_readout(emu)
    # Start capacitor history at the solved DC operating point, not an
    # unrelated uncharged startup. No JAD/ADC voltage source overrides.
    from pcb_emu.components import Capacitor
    for component in emu.components:
        if isinstance(component, Capacitor):
            pins = emu._ci[id(component)]
            emu.cap_history[id(component)] = emu.x[pins['1']] - emu.x[pins['2']]
    reference = [emu.read(emu.boards['MB'].pin('JAD', str(i + 1))) for i in range(10)]
    try:
        emu.run(ticks=40)
        if not pico.done:
            raise RuntimeError('Pico firmware has not finished')
        report = {'image_index': args.index, 'analog_nominal_prediction': nominal['class'],
                  'wired_jad_voltages': reference, 'addresses': [d.address for d in devices],
                  'ads1115_codes': pico.globals['scores'],
                  'pico_prediction': pico.globals['prediction'], 'simulated_seconds': emu.time,
                  'scope': 'averaged PWM, endpoint ADC sampling, transaction-level I2C, ideal ADC input impedance'}
    finally:
        pico.close()
    check_sources()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
