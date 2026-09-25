#!/usr/bin/env python3
"""Freeze explicit budget inputs before measuring; never calls a solver."""
import argparse
import json
from pathlib import Path
from freeze_joint import suite as joint_suite

ROOT = Path(__file__).resolve().parents[1]


def suite():
    base = joint_suite()
    cases = []
    for c in base['cases'][:8] + [base['cases'][i] for i in (8, 12, 16, 19, 20)]:
        b = c['problem']['error_budget']
        cases.append(dict(c, budgets=[b, 0, max(0, b-1), min(12484800, b*2+1), b]))
    for name, settings in [('zero-time', {'total_time_limit': 0}),
                           ('zero-nodes', {'total_node_limit': 0}),
                           ('incumbent-only', {'node_limit': 0})]:
        cases.append(dict(base['cases'][1], name=name, budgets=[300, 299, 0], settings=settings))
    return {'schema_version': 1, 'seed': base['seed'],
            'settings': {'time_limit': 5.0, 'total_time_limit': 20.0, 'node_limit': 20000,
                         'total_node_limit': 50000, 'section_size': 3},
            'cases': cases,
            'measurement': 'Fresh process per case; perf_counter including search, validation and exports; Linux ru_maxrss KiB including imports; all outcomes retained.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = ROOT/'experiments/explorer-suite.json'
    data = suite()
    if args.check:
        assert json.loads(path.read_text()) == data
        print(f"Frozen explorer suite reproduced: {len(data['cases'])} cases")
    else:
        with path.open('x') as stream:
            stream.write(json.dumps(data, indent=2)+'\n')
        print(f"Frozen {len(data['cases'])} explorer cases; no measurements run")


if __name__ == '__main__':
    main()
