#!/usr/bin/env python3
"""Recreate the premeasurement benchmark inputs; does not invoke any solver."""
import argparse
import json
from pathlib import Path
import random

from joint_cases import SEED, inventory, named_cases, problem

ROOT = Path(__file__).resolve().parents[1]


def suite():
    cases = [{'name': name, 'problem': p, 'inventory': inv} for name, p, inv in named_cases()]
    rng = random.Random(SEED + 1)
    for i, (w, h) in enumerate([(4, 3), (4, 4), (6, 4), (8, 8)]):
        rgbs = [(0, 0, 0), (100, 80, 20), (255, 255, 255)]
        for mode in ('blocks', 'checker', 'noise'):
            pixels = [rgbs[((x//2+y//2) % 3 if mode == 'blocks' else
                            (x+y) % 3 if mode == 'checker' else rng.randrange(3))]
                      for y in range(h) for x in range(w)]
            inv = inventory([(w*h//3+2, w*h//4+1, w*h//8+1)] * 3)
            cases.append({'name': f'{w}x{h}-{mode}', 'problem': problem(w, h, pixels, w*h*15000, rgbs), 'inventory': inv})
    cases.append({'name': 'eight-colors-64-cells',
                  'problem': problem(8, 8, [(i*30,)*3 for i in range(8)]*8, 64*10000, [(i*30,)*3 for i in range(8)]),
                  'inventory': inventory([(8, 4, 2)]*8)})
    cases.append({'name': 'no-nodes-with-incumbent', 'problem': cases[1]['problem'], 'inventory': cases[1]['inventory'], 'node_limit': 0})
    cases.append({'name': 'no-time-without-incumbent', 'problem': cases[1]['problem'], 'inventory': cases[1]['inventory'], 'time_limit_seconds': 0})
    return {'schema_version': 1, 'seed': SEED+1, 'settings': {'node_limit': 20000, 'time_limit_seconds': 5.0},
            'baseline': 'existing exact min-cost color assignment with color capacity = total piece area, then fixed-color packing',
            'measurement': 'one fresh child process per case/method; perf_counter elapsed and Linux ru_maxrss KiB; retain all outcomes',
            'cases': cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = ROOT / 'experiments/joint-suite.json'
    data = suite()
    if args.check:
        assert json.loads(path.read_text()) == data
        print(f'Frozen suite reproduced: {len(data["cases"])} cases, seed {data["seed"]}')
    else:
        with path.open('x') as stream:
            stream.write(json.dumps(data, indent=2) + '\n')
        print(f'Frozen {len(data["cases"])} inputs; no solver measurements performed')


if __name__ == '__main__':
    main()
