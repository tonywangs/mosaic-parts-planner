#!/usr/bin/env python3
"""Seeded oracle and bounded CPU comparisons; measurements are never replayed."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

from PIL import __version__ as pillow_version
from mosaic_parts import __version__
from mosaic_parts.packing_solver import solve
from mosaic_parts.packing_validate import validate_placements
from packing_baselines import baseline
from packing_cases import SEED, benchmark_cases, exhaustive, tiny_cases

SETTINGS = {"time_limit": 2.0, "node_limit": 20_000}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def worker(case, algorithm):
    g, inv = case['grid'], case['inventory']
    start, cpu = time.perf_counter(), time.process_time()
    if algorithm == 'exact':
        answer = solve(g, inv, **case['settings'])
    else:
        p = baseline(g, inv, only_units=algorithm == 'all_1x1')
        answer = {'status': 'feasible' if p is not None else 'no_baseline_solution',
                  'termination': 'completed', 'piece_count': None if p is None else len(p),
                  'placements': p, 'nodes': None, 'lower_bound': None}
    wall, cpu = time.perf_counter() - start, time.process_time() - cpu
    if answer['placements'] is not None:
        validate_placements(g, inv, answer['placements'])
    answer['placement_sha256'] = None if answer['placements'] is None else digest(answer['placements'])
    del answer['placements']
    # Linux's mm high-water mark resets on exec, unlike ru_maxrss, which can
    # include the larger benchmark parent's pre-exec fork memory footprint.
    proc_status = Path('/proc/self/status')
    if sys.platform.startswith('linux') and proc_status.exists():
        hwm = next(line for line in proc_status.read_text().splitlines() if line.startswith('VmHWM:'))
        peak = int(hwm.split()[1]) * 1024
        source = 'Linux /proc/self/status VmHWM (KiB converted to bytes)'
    else:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
        source = 'getrusage ru_maxrss; may include inherited pre-exec memory'
    answer.update(wall_seconds=wall, cpu_seconds=cpu, peak_rss_bytes=peak, peak_rss_source=source)
    return answer


def run():
    oracle_results = []
    for name, g, inv in tiny_cases():
        expected = exhaustive(g, inv)
        actual = solve(g, inv, time_limit=30, node_limit=1_000_000)
        assert actual['status'] == ('infeasible' if expected['piece_count'] is None else 'optimal'), name
        assert actual['piece_count'] == expected['piece_count'], name
        oracle_results.append({'case': name, 'grid': g, 'inventory': inv, 'oracle': expected,
                               'solver': {k: v for k, v in actual.items() if k != 'placements'},
                               'placement_sha256': None if actual['placements'] is None else digest(actual['placements'])})
    inputs = [{'case': name, 'grid': g, 'inventory': inv, 'settings': SETTINGS} for name, g, inv in benchmark_cases()]
    for name, g, inv in [benchmark_cases()[0], benchmark_cases()[6]]:
        inputs.append({'case': name + '_zero_nodes', 'grid': g, 'inventory': inv,
                       'settings': {**SETTINGS, 'node_limit': 0}})
    inputs.append({'case': 'zero_time', 'grid': inputs[0]['grid'], 'inventory': inputs[0]['inventory'],
                   'settings': {**SETTINGS, 'time_limit': 0}})
    results = []
    for case in inputs:
        measurements = {}
        for algorithm in ('exact', 'greedy', 'all_1x1'):
            process = subprocess.run([sys.executable, __file__, '--worker', algorithm],
                                     input=json.dumps(case), capture_output=True, text=True, check=True, timeout=15)
            measurements[algorithm] = json.loads(process.stdout)
        results.append({**case, 'measurements': measurements})
    return {'schema_version': 1, 'seed': SEED, 'recorded_utc': datetime.now(timezone.utc).isoformat(),
            'versions': {'planner': __version__, 'python': platform.python_version(), 'pillow': pillow_version,
                         'solver': 'integer-dfs-v1'},
            'platform': platform.platform(), 'machine': platform.machine(),
            'measurement': 'One fresh subprocess per case/algorithm. Wall and CPU encompass the algorithm call, including its internal validation, '
                           'but exclude process startup and the subsequent independent validation. Peak RSS is the worker high-water mark including imports and validation; see peak_rss_source. '
                           'No speed significance or physical validation is claimed.',
            'oracle_settings': {'time_limit': 30, 'node_limit': 1_000_000, 'max_cells': 12},
            'oracle_cases': oracle_results, 'benchmarks': results}


def check_recorded(actual, expected):
    assert actual['seed'] == expected['seed'] and actual['versions'] == expected['versions']
    assert actual['oracle_cases'] == expected['oracle_cases'], 'tiny oracle results changed'
    assert len(actual['benchmarks']) == len(expected['benchmarks'])
    for a, e in zip(actual['benchmarks'], expected['benchmarks']):
        assert all(a[k] == e[k] for k in ('case', 'grid', 'inventory', 'settings'))
        for algorithm in a['measurements']:
            fresh, old = a['measurements'][algorithm], e['measurements'][algorithm]
            # Wall cutoffs may change the explored prefix or found solution.
            # All incumbents were validated in the worker regardless of status.
            if fresh['termination'] != 'time_limit' and old['termination'] != 'time_limit':
                for key in ('status', 'termination', 'piece_count', 'nodes', 'lower_bound', 'placement_sha256'):
                    assert fresh[key] == old[key], (a['case'], algorithm, key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', choices=('exact', 'greedy', 'all_1x1'))
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--output', type=Path)
    actions.add_argument('--check', type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(json.load(sys.stdin), args.worker)))
        return
    result = run()
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + '\n')
        print(f"Saved {len(result['oracle_cases'])} exhaustive cases and {len(result['benchmarks'])} three-way comparisons")
    elif args.check:
        check_recorded(result, json.loads(args.check.read_text()))
        print(f"Rechecked {len(result['oracle_cases'])} exhaustive cases and {len(result['benchmarks'])} comparisons; timings remeasured, not equality-tested")
    else:
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
