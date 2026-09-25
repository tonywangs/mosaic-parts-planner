#!/usr/bin/env python3
"""Measure the frozen suite in isolated child processes; retain negative results."""
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
from mosaic_parts.joint_solver import solve
from mosaic_parts.joint_validate import validate
from mosaic_parts.model import Color, InputError
from mosaic_parts.packing_solver import solve as pack
from mosaic_parts.solver import assign

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / 'experiments/joint-suite.json'


def sequential(p, inv, seconds, nodes):
    start = time.monotonic()
    if seconds == 0:
        return {'status': 'unknown', 'termination': 'time_limit', 'piece_count': None, 'image_error': None}
    capacity = [0] * len(p['colors'])
    for item in inv['pieces']:
        a, b = map(int, item['shape'].split('x'))
        capacity[item['color_id']-1] += item['available']*a*b
    colors = [Color(c['name'], tuple(c['rgb']), capacity[i]) for i, c in enumerate(p['colors'])]
    try:
        assigned = assign([tuple(rgb) for rgb in p['pixels']], colors)
    except InputError:
        return {'status': 'infeasible', 'termination': 'insufficient_color_area', 'piece_count': None, 'image_error': None}
    error = sum(sum((a-b)**2 for a, b in zip(rgb, colors[c].rgb)) for rgb, c in zip(p['pixels'], assigned))
    if error > p['error_budget']:
        return {'status': 'infeasible', 'termination': 'minimum_color_error_exceeds_budget', 'piece_count': None, 'image_error': error}
    remaining = seconds - (time.monotonic()-start)
    if remaining <= 0:
        return {'status': 'unknown', 'termination': 'time_limit', 'piece_count': None, 'image_error': error}
    w = p['width']
    grid = {k: p[k] for k in ('schema_version', 'width', 'height', 'colors')} | {
        'grid': [[c+1 for c in assigned[i:i+w]] for i in range(0, len(assigned), w)]}
    answer = pack(grid, inv, time_limit=remaining, node_limit=nodes)
    if answer['placements'] is not None:
        validate(p, inv, answer['placements'])
    return {k: answer[k] for k in ('status', 'termination', 'piece_count', 'nodes')} | {'image_error': error}


def worker(index, method):
    suite = json.loads(SUITE.read_text())
    case = suite['cases'][index]
    settings = suite['settings'] | {k: case[k] for k in ('node_limit', 'time_limit_seconds') if k in case}
    p, inv = case['problem'], case['inventory']
    start = time.perf_counter()
    if method == 'joint':
        answer = solve(p, inv, time_limit=settings['time_limit_seconds'], node_limit=settings['node_limit'])
        if answer['placements'] is not None:
            validate(p, inv, answer['placements'])
        answer = {k: v for k, v in answer.items() if k != 'placements'}
    else:
        answer = sequential(p, inv, settings['time_limit_seconds'], settings['node_limit'])
    elapsed = time.perf_counter()-start
    return {'case': case['name'], 'method': method, 'settings': settings, 'result': answer,
            'feasible': answer['piece_count'] is not None, 'elapsed_seconds': elapsed,
            'peak_process_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def run():
    suite = json.loads(SUITE.read_text())
    results = []
    for i, case in enumerate(suite['cases']):
        for method in ('joint', 'sequential'):
            process = subprocess.run([sys.executable, __file__, '--worker', str(i), '--method', method],
                                     capture_output=True, text=True, timeout=15, check=True)
            result = json.loads(process.stdout)
            results.append(result)
            print(f"{case['name']} {method}: {result['result']['status']}, {result['result']['piece_count']} pieces", file=sys.stderr)
    return {'schema_version': 1, 'recorded_utc': datetime.now(timezone.utc).isoformat(),
            'suite_sha256': hashlib.sha256(SUITE.read_bytes()).hexdigest(),
            'versions': {'planner': __version__, 'python': platform.python_version(), 'pillow': pillow_version},
            'platform': platform.platform(),
            'measurement': 'One fresh process per row. Wall includes algorithm and validation, excludes process startup. Linux ru_maxrss KiB includes imports. Single measurements, no speed significance claim.',
            'baseline_status_scope': 'Sequential optimal/infeasible refers to its fixed-color grid, not all possible recolorings.',
            'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=int)
    parser.add_argument('--method', choices=('joint', 'sequential'))
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--record', type=Path)
    action.add_argument('--check', type=Path)
    args = parser.parse_args()
    if args.worker is not None:
        print(json.dumps(worker(args.worker, args.method)))
        return
    result = run()
    if args.record:
        args.record.write_text(json.dumps(result, indent=2)+'\n')
    if args.check:
        previous = json.loads(args.check.read_text())
        assert previous['suite_sha256'] == result['suite_sha256'], 'frozen inputs changed'
        assert len(previous['results']) == len(result['results'])
        for old, new in zip(previous['results'], result['results']):
            assert (old['case'], old['method'], old['settings']) == (new['case'], new['method'], new['settings'])
            # No comparison of elapsed/RSS. Node-limited search is deterministic;
            # if either run hits a wall deadline only invariant checks apply.
            if 'time_limit' not in (old['result']['termination'], new['result']['termination']):
                assert old['result'] == new['result'], (old, new)
            assert new['elapsed_seconds'] >= 0 and new['peak_process_rss_kib'] > 0
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
