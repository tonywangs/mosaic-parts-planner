import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from mosaic_parts.explorer import explore, validate_report, selected_plan
from mosaic_parts.explorer_export import export_comparison, export_selected, read_report, explore_image
from mosaic_parts.joint_solver import solve
from mosaic_parts.model import InputError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from joint_cases import tiny_cases, exhaustive, named_cases
from check_joint import check


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        _, self.p, self.inv = named_cases()[1]

    def test_248_seeded_instances_multiple_budgets_against_exhaustive(self):
        for name, p, inv in tiny_cases():
            b = p['error_budget']
            budgets = [b, 0, max(0, b-1), min(12484800, b+1), b]
            report = explore(p, inv, budgets, time_limit=30, total_time_limit=300,
                             node_limit=2_000_000, total_node_limit=2_000_000)
            for outcome in report['outcomes']:
                expected = exhaustive(p | {'error_budget': outcome['budget']}, inv)
                self.assertEqual(outcome['result']['piece_count'], expected, (name, outcome))
                self.assertEqual(outcome['result']['status'], 'infeasible' if expected is None else 'optimal')
            self.assertEqual(report['outcomes'][0], report['outcomes'][-1])

    def test_boundary_dedup_order_and_ties(self):
        r = explore(self.p, self.inv, [301, 0, 299, 300, 301])
        self.assertEqual([o['result']['piece_count'] for o in r['outcomes']], [1, 2, 2, 1, 1])
        self.assertEqual(len(r['plans']), 2)
        self.assertEqual(r['outcomes'][0]['plan_id'], r['outcomes'][3]['plan_id'])
        self.assertTrue(all(p['nondominated_among_returned'] for p in r['plans']))
        _, p, inv = named_cases()[5]
        self.assertEqual(explore(p, inv, [299, 300])['outcomes'][1]['result']['piece_count'], 2)

    def test_interruptions(self):
        r = explore(self.p, self.inv, [300, 0], node_limit=0)
        self.assertEqual([o['result']['status'] for o in r['outcomes']], ['feasible', 'feasible'])
        for kw, reason in [({'time_limit': 0}, 'time_limit'), ({'total_time_limit': 0}, 'total_time_limit'),
                           ({'total_node_limit': 0}, 'total_node_limit'), ({'cancelled': lambda: True}, 'cancelled')]:
            r = explore(self.p, self.inv, [300, 0], **kw)
            self.assertTrue(all(o['result']['status'] == 'unknown' for o in r['outcomes']))
            self.assertEqual(r['outcomes'][0]['result']['termination'], reason)
        r = explore(self.p, self.inv, [300, 299, 0], total_node_limit=1)
        self.assertEqual(r['nodes_consumed'], 1)
        self.assertEqual(r['outcomes'][1]['result']['termination'], 'total_node_limit')
        # Inject cancellation at every check, including before/after greedy incumbents.
        statuses = set()
        for stop in range(1, 20):
            calls = [0]
            def cancel():
                calls[0] += 1
                return calls[0] >= stop
            r = explore(self.p, self.inv, [300, 299, 0], cancelled=cancel)
            validate_report(r)
            statuses.add(r['outcomes'][0]['result']['status'])
        self.assertTrue({'unknown', 'feasible', 'optimal'} <= statuses)
        ticks = [0]
        def clock():
            ticks[0] += 1
            return ticks[0] * .01
        r = explore(self.p, self.inv, [300, 299, 0], clock=clock, total_time_limit=.1)
        self.assertEqual(r['outcomes'][-1]['result']['termination'], 'total_time_limit')

    def test_bad_inputs_and_solver_results(self):
        for budgets in [[], list(range(13)), [True], [-1], [12484801], ['3'], [1.0]]:
            with self.assertRaises(InputError):
                explore(self.p, self.inv, budgets)
        for kw in [{'total_time_limit': float('nan')}, {'total_node_limit': True}, {'total_time_limit': 301}]:
            with self.assertRaises(InputError):
                explore(self.p, self.inv, [0], **kw)
        answer = solve(self.p, self.inv)
        for field, value in [('piece_count', 99), ('image_error', -1), ('status', 'infeasible'),
                             ('nodes', -1), ('placements', []), ('termination', 'fake')]:
            with patch('mosaic_parts.explorer.solve', return_value=answer | {field: value}):
                with self.assertRaises(InputError):
                    explore(self.p, self.inv, [300])

    def test_saved_plan_and_atomic_failure(self):
        r = explore(self.p, self.inv, [299, 300, 300])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('mosaic_parts.explorer.solve', side_effect=AssertionError('must not solve')):
                export_comparison(r, root/'sweep')
                saved = read_report(root/'sweep/comparison.json')
                for entry in saved['plans']:
                    path = root/entry['id']
                    export_selected(saved, entry['id'], path)
                    check(path, entry['plan']['problem'], self.inv)
                with self.assertRaises(InputError):
                    export_comparison(r, root/'sweep')
                with self.assertRaises(InputError):
                    export_selected(saved, 'missing', root/'missing')
            with patch('mosaic_parts.explorer_export.comparison_html', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    export_comparison(r, root/'failed')
            self.assertFalse((root/'failed').exists())
            self.assertFalse(list(root.glob('.failed-*')))
            (root/'link').symlink_to(root/'absent')
            with self.assertRaises(InputError):
                export_comparison(r, root/'link')
            with patch('mosaic_parts.explorer_export.load_problem', side_effect=AssertionError('must not decode')):
                with self.assertRaises(InputError):
                    explore_image('bad', 'bad', 'bad', root/'sweep', 1, 1, [0])
            for raw in ['{}', '{"schema_version":1,"schema_version":1}', '['*2000]:
                (root/'bad.json').write_text(raw)
                with self.assertRaises(InputError):
                    read_report(root/'bad.json')

    def test_tampering_rejected(self):
        r = explore(self.p, self.inv, [299, 300])
        mutations = [lambda x: x['plans'][0]['plan']['placements'][0].update(rotation=90),
                     lambda x: x['outcomes'][0]['result'].update(image_error=99),
                     lambda x: x['plans'][0].update(nondominated_among_returned=False),
                     lambda x: x['outcomes'][0].update(plan_id='missing'),
                     lambda x: x.update(nodes_consumed=-1),
                     lambda x: x['plans'][0]['plan']['problem']['pixels'][0].__setitem__(0, 255)]
        for mutate in mutations:
            damaged = copy.deepcopy(r)
            mutate(damaged)
            with self.assertRaises(InputError):
                validate_report(damaged)
        self.assertEqual(selected_plan(r, 'plan-1')['result']['piece_count'], 2)


if __name__ == '__main__':
    unittest.main()
