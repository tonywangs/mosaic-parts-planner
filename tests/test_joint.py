import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mosaic_parts.joint_export import export, load_problem, optimize
from mosaic_parts.joint_inputs import normalize_problem
from mosaic_parts.joint_solver import solve
from mosaic_parts.joint_validate import validate, validate_plan
from mosaic_parts.model import InputError
from mosaic_parts.packing_solver import SolverError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from joint_cases import exhaustive, inventory, named_cases, problem, tiny_cases


class JointTests(unittest.TestCase):
    def test_248_exhaustive_cases(self):
        for name, p, inv in tiny_cases():
            with self.subTest(case=name):
                expected = exhaustive(p, inv)
                answer = solve(p, inv, time_limit=30, node_limit=2_000_000)
                self.assertEqual(answer['status'], 'infeasible' if expected is None else 'optimal')
                self.assertEqual(answer['piece_count'], expected)
                if expected is not None:
                    checked = validate(p, inv, answer['placements'])
                    self.assertEqual(checked['image_error'], answer['image_error'])

    def test_boundary_and_rotation(self):
        counts = [solve(p, inv)['piece_count'] for _, p, inv in named_cases()]
        self.assertEqual(counts, [2, 1, 1, None, 1, 2, None, None])
        _, p, inv = named_cases()[2]
        self.assertEqual(solve(p, inv)['placements'][0]['rotation'], 90)

    def test_bounded_search_statuses(self):
        _, p, inv = named_cases()[1]
        result = solve(p, inv, node_limit=0)
        self.assertEqual((result['status'], result['termination']), ('feasible', 'node_limit'))
        self.assertEqual(solve(p, inv, time_limit=0)['status'], 'unknown')
        _, p, inv = named_cases()[-1]
        self.assertEqual(solve(p, inv, node_limit=0)['status'], 'unknown')
        self.assertEqual(solve(p, inv)['status'], 'infeasible')

    def test_clock_termination_and_failure(self):
        _, p, inv = named_cases()[1]
        for stop in (1, 3, 6, 9):
            ticks = iter([0] * stop + [1000] * 100)
            result = solve(p, inv, clock=lambda: next(ticks))
            if result['placements']:
                validate(p, inv, result['placements'])
            self.assertIn(result['status'], ('unknown', 'feasible', 'optimal'))
        with patch('mosaic_parts.joint_solver.Candidate', side_effect=RuntimeError('injected')):
            with self.assertRaises(SolverError):
                solve(p, inv)

    def test_backtracking_finds_incumbent_after_both_greedies_fail(self):
        _, p, inv = next(case for case in tiny_cases() if case[0] == 'seed-260925-7')
        self.assertEqual(solve(p, inv, node_limit=0)['status'], 'unknown')
        answer = solve(p, inv, node_limit=7)
        self.assertEqual((answer['status'], answer['termination']), ('feasible', 'node_limit'))
        self.assertEqual(answer['piece_count'], 4)
        validate(p, inv, answer['placements'])
        # A cooperative wall stop also retains a DFS-discovered incumbent.
        ticks = [0]
        def clock():
            ticks[0] += 1
            return ticks[0] / 100
        # Sweep interruption points without depending on real machine speed.
        observed = set()
        for limit in range(1, 55):
            ticks[0] = 0
            result = solve(p, inv, time_limit=limit / 100, clock=clock)
            observed.add(result['status'])
            if result['placements']:
                validate(p, inv, result['placements'])
        self.assertTrue({'unknown', 'feasible', 'optimal'} <= observed)

    def test_malformed_and_resource_bounds(self):
        _, p, inv = named_cases()[1]
        for key, value in [('error_budget', True), ('error_budget', -1), ('error_budget', 12484801),
                           ('width', 65), ('height', 33), ('pixels', [[0, 0, 0]]),
                           ('pixels', [[0, 0, 0], [False, 1, 2]]), ('schema_version', True),
                           ('colors', p['colors'] * 5)]:
            with self.subTest(key=key, value=value), self.assertRaises(InputError):
                normalize_problem(p | {key: value})
        for kw in ({'time_limit': float('nan')}, {'time_limit': 301}, {'node_limit': 2_000_001}, {'node_limit': True}):
            with self.assertRaises(InputError):
                solve(p, inv, **kw)
        inv['pieces'][0]['available'] = -1
        with self.assertRaises(InputError):
            solve(p, inv)

    def test_maximum_cells_colors_and_candidates(self):
        p = problem(8, 8, [(0, 0, 0)] * 64, 12484800, [(i*30,)*3 for i in range(8)])
        inv = inventory([(64, 32, 16)] * 8)
        result = solve(p, inv)
        self.assertEqual(result['status'], 'optimal')
        self.assertEqual(result['piece_count'], 16)
        self.assertLessEqual(result['candidates_considered'], 2048)
        validate(p, inv, result['placements'])

    def test_independent_validator_rejects_corruption(self):
        _, p, inv = named_cases()[0]
        placements = solve(p, inv)['placements']
        mutations = [('rotation', 90), ('x', 5), ('width', 2), ('id', False), ('color_id', 99), ('shape', '2x2')]
        for key, value in mutations:
            altered = copy.deepcopy(placements)
            altered[0][key] = value
            with self.subTest(key=key), self.assertRaises(InputError):
                validate(p, inv, altered)
        with self.assertRaises(InputError):
            validate(p, inv, placements[:-1])
        altered = copy.deepcopy(placements)
        altered[1]['x'] = altered[0]['x']
        with self.assertRaises(InputError):
            validate(p, inv, altered)
        altered = copy.deepcopy(placements)
        altered[1]['color_id'] = 1
        with self.assertRaises(InputError):
            validate(p, inv, altered)  # exact budget violated
        scarce = copy.deepcopy(inv)
        scarce['pieces'][0]['available'] = 0
        with self.assertRaises(InputError):
            validate(p, scarce, placements)

    def test_atomic_export_and_metadata_tampering(self):
        _, p, inv = named_cases()[1]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            out = root / 'plan'
            export(p, inv, out, section_size=1)
            plan = json.loads((out / 'placements.json').read_text())
            validate_plan(plan, p, inv)
            for field, value in [('image_error', 0), ('piece_count', True), ('status', 'infeasible')]:
                altered = copy.deepcopy(plan)
                altered['result'][field] = value
                with self.assertRaises(InputError):
                    validate_plan(altered, p, inv)
            for field, value in [('recolored_cells', []), ('input_grid', {}), ('problem', {})]:
                with self.assertRaises(InputError):
                    validate_plan(plan | {field: value}, p, inv)
            original = {path.name: path.read_bytes() for path in out.iterdir()}
            with self.assertRaises(InputError):
                export(p, inv, out)
            self.assertEqual(original, {path.name: path.read_bytes() for path in out.iterdir()})
            with patch('mosaic_parts.joint_export.instructions', side_effect=OSError('disk failed')):
                with self.assertRaises(OSError):
                    export(p, inv, root / 'failed')
            self.assertEqual(list(root.iterdir()), [out])
            invalid = solve(p, inv)
            invalid['image_error'] += 1
            with patch('mosaic_parts.joint_export.solve', return_value=invalid):
                with self.assertRaises(InputError):
                    export(p, inv, root / 'invalid')
            self.assertFalse((root / 'invalid').exists())
            with patch('mosaic_parts.joint_export.solve', return_value={'status': 'optimal', 'placements': None}):
                with self.assertRaises(InputError):
                    export(p, inv, root / 'false-solution')
            with patch('mosaic_parts.joint_export.solve', side_effect=SolverError('injected failure')):
                with self.assertRaises(SolverError):
                    export(p, inv, root / 'solver-failure')
            export(p, inv, root / 'unknown', time_limit=0)
            self.assertEqual([f.name for f in (root / 'unknown').iterdir()], ['solve.json'])
            _, p2, inv2 = named_cases()[-1]
            export(p2, inv2, root / 'infeasible')
            self.assertEqual([f.name for f in (root / 'infeasible').iterdir()], ['solve.json'])

    def test_visible_bundle_checker_detects_tampering(self):
        from check_joint import check
        _, p, inv = named_cases()[1]
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'plan'
            export(p, inv, out)
            check(out, p, inv)
            html = (out / 'instructions.html').read_text()
            (out / 'instructions.html').write_text(html.replace('<span>P1</span>', '<span>P99</span>', 1))
            with self.assertRaises(AssertionError):
                check(out, p, inv)
            (out / 'instructions.html').write_text(html)
            # Explicitly corrupt a used-count column without relying on fixture counts.
            import csv as csv_module
            with (out / 'parts.csv').open(newline='') as stream:
                rows = list(csv_module.reader(stream))
            rows[1][5] = '999'
            with (out / 'parts.csv').open('w', newline='') as stream:
                csv_module.writer(stream).writerows(rows)
            with self.assertRaises(AssertionError):
                check(out, p, inv)

    def test_cli_sample_and_repeatability(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for seed in ('11', '99'):
                out = root / seed
                args = [sys.executable, '-m', 'mosaic_parts', 'optimize', str(ROOT / 'examples/source.png'),
                        '--palette', str(ROOT / 'examples/joint-palette.json'), '--inventory', str(ROOT / 'examples/pieces.json'),
                        '--width', '6', '--height', '4', '--error-budget', '200000', '--output', str(out), '--section-size', '3']
                run = subprocess.run(args, env=os.environ | {'PYTHONHASHSEED': seed}, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                plan = json.loads((out / 'placements.json').read_text())
                p, _ = load_problem(ROOT / 'examples/source.png', ROOT / 'examples/joint-palette.json', 6, 4, 200000)
                validate_plan(plan, p, json.loads((ROOT / 'examples/pieces.json').read_text()))
            for path in (root / '11').iterdir():
                self.assertEqual(path.read_bytes(), (root / '99' / path.name).read_bytes())
            bad = subprocess.run(args[:-4] + ['--output', str(root / 'bad'), '--error-budget', '-1'], capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2)
            self.assertNotIn('Traceback', bad.stderr)


if __name__ == '__main__':
    unittest.main()
