#!/usr/bin/env python3
"""Measure frozen budget sweeps without dropping unresolved outcomes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import time

from PIL import __version__ as pillow_version
from mosaic_parts.explorer import explore
from mosaic_parts.explorer_export import export_comparison

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT/'experiments/explorer-suite.json'


def worker(index):
    suite = json.loads(SUITE.read_text())
    case = suite['cases'][index]
    settings = suite['settings'] | case.get('settings', {})
    start = time.perf_counter()
    report = explore(case['problem'], case['inventory'], case['budgets'], **settings)
    with tempfile.TemporaryDirectory(prefix='explorer-bench-') as tmp:
        out = Path(tmp)/'out'
        export_comparison(report, out)
        sizes = {p.name: p.stat().st_size for p in sorted(out.iterdir())}
    return {'case': case['name'], 'settings': settings, 'outcomes': report['outcomes'],
            'unique_plans': len(report['plans']), 'nodes_consumed': report['nodes_consumed'],
            'elapsed_seconds': time.perf_counter()-start,
            'peak_process_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'output_bytes': sizes}


def run():
    suite = json.loads(SUITE.read_text())
    results = []
    for i, c in enumerate(suite['cases']):
        proc = subprocess.run([sys.executable, __file__, '--worker', str(i)], capture_output=True,
                              text=True, check=True, timeout=90)
        row = json.loads(proc.stdout)
        results.append(row)
        print(f"{c['name']}: {row['unique_plans']} plans, {row['elapsed_seconds']:.3f}s", file=sys.stderr)
    return {'schema_version': 1, 'recorded_utc': datetime.now(timezone.utc).isoformat(),
            'suite_sha256': hashlib.sha256(SUITE.read_bytes()).hexdigest(), 'platform': platform.platform(),
            'versions': {'python': platform.python_version(), 'pillow': pillow_version},
            'measurement': suite['measurement'], 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=int)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--record', type=Path)
    action.add_argument('--check', type=Path)
    args = parser.parse_args()
    if args.worker is not None:
        print(json.dumps(worker(args.worker)))
        return
    result = run()
    if args.record:
        with args.record.open('x') as stream:
            stream.write(json.dumps(result, indent=2)+'\n')
    if args.check:
        old = json.loads(args.check.read_text())
        assert old['suite_sha256'] == result['suite_sha256']
        assert len(old['results']) == len(result['results'])
        for a, b in zip(old['results'], result['results']):
            assert (a['case'], a['settings']) == (b['case'], b['settings'])
            reasons = [o['result']['termination'] for row in (a, b) for o in row['outcomes']]
            if not any('time_limit' in reason for reason in reasons):
                for key in ('outcomes', 'unique_plans', 'nodes_consumed', 'output_bytes'):
                    assert a[key] == b[key], (a['case'], key)
            assert b['elapsed_seconds'] >= 0 and b['peak_process_rss_kib'] > 0
    print(f"Validated {len(result['results'])} frozen explorer benchmarks")


if __name__ == '__main__':
    main()
