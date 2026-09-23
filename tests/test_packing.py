import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mosaic_parts.export import write_json
from mosaic_parts.model import InputError
from mosaic_parts.packing_export import pack
from mosaic_parts.packing_inputs import normalize_grid, normalize_inventory, read_json, validate_settings
from mosaic_parts.packing_solver import SolverError, greedy, solve
from mosaic_parts.packing_validate import validate_placements, validate_plan

ROOT = Path(__file__).resolve().parents[1]
# Scripts are independent checks and fixtures, not package implementation.
sys.path.insert(0, str(ROOT / "scripts"))
from packing_cases import exhaustive, grid, inventory, named_cases, tiny_cases
from check_packing import check


class PackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.g = grid([[1] * 4 for _ in range(4)])
        self.inv = inventory([(16, 8, 4)])
        self.gpath, self.ipath = self.root / "grid.json", self.root / "inventory.json"
        self.inputs()

    def inputs(self):
        write_json(self.gpath, self.g)
        write_json(self.ipath, self.inv)

    def test_308_cases_against_independent_exhaustive_oracle(self):
        for name, g, inv in tiny_cases():
            with self.subTest(case=name):
                expected = exhaustive(g, inv)
                actual = solve(g, inv, time_limit=30, node_limit=1_000_000)
                self.assertEqual(actual["status"], "infeasible" if expected["piece_count"] is None else "optimal")
                self.assertEqual(actual["piece_count"], expected["piece_count"])
                if actual["placements"] is not None:
                    validate_placements(g, inv, actual["placements"])
        self.assertGreater(exhaustive(*named_cases()[2][1:])["optimal_tilings"], 1)

    def test_backtracking_finds_and_retains_incumbent_after_greedy_failure(self):
        _, g, inv = named_cases()[6]
        self.assertIsNone(greedy(g, inv))
        self.assertEqual(solve(g, inv, node_limit=9)["status"], "unknown")
        partial = solve(g, inv, node_limit=10)
        self.assertEqual((partial["status"], partial["piece_count"]), ("feasible", 5))
        validate_placements(g, inv, partial["placements"])
        self.assertEqual(solve(g, inv)["status"], "optimal")

    def test_rotation_is_shared_inventory_and_explicit(self):
        g, inv = grid([[1, 1]]), inventory([(0, 1, 0)])
        a = solve(g, inv)
        self.assertEqual(a["placements"][0]["rotation"], 90)
        inv["pieces"][1]["rotate"] = False
        self.assertEqual(solve(g, inv)["status"], "infeasible")
        g = grid([[1, 1], [1, 1]])
        inv["pieces"][1]["rotate"] = True
        self.assertEqual(solve(g, inv)["status"], "infeasible")

    def test_limits_with_and_without_incumbents(self):
        a = solve(self.g, self.inv, node_limit=0)
        self.assertEqual((a["status"], a["termination"], a["nodes"]), ("feasible", "node_limit", 0))
        validate_placements(self.g, self.inv, a["placements"])
        a = solve(self.g, self.inv, time_limit=0)
        self.assertEqual((a["status"], a["termination"], a["placements"]), ("unknown", "time_limit", None))
        a = solve(grid([[1]]), inventory([(0, 0, 0)]), node_limit=0)
        self.assertEqual((a["status"], a["termination"]), ("unknown", "node_limit"))
        self.assertEqual(solve(grid([[1]]), inventory([(0, 0, 0)]))["status"], "infeasible")

    def test_clock_deadline_in_preprocessing_and_after_greedy(self):
        ticks = iter([0, 0, 100])
        a = solve(self.g, self.inv, time_limit=1, clock=lambda: next(ticks))
        self.assertEqual((a["status"], a["termination"]), ("unknown", "time_limit"))
        # start + initial check + 16 anchors + four greedy placements; then DFS.
        ticks = iter([0] * 22 + [2])
        a = solve(self.g, self.inv, time_limit=1, clock=lambda: next(ticks))
        self.assertEqual((a["status"], a["termination"]), ("feasible", "time_limit"))
        validate_placements(self.g, self.inv, a["placements"])

    def test_validator_rejects_corruption(self):
        good = solve(self.g, self.inv)["placements"]
        bad = []
        for key, value in (("x", -1), ("y", 99), ("x", True), ("y", 0.0), ("width", 1),
                           ("height", 0), ("rotation", 90), ("shape", "2x1"), ("color_id", 2),
                           ("id", 9), ("shape", [])):
            p = copy.deepcopy(good)
            p[0][key] = value
            bad.append(p)
        p = copy.deepcopy(good)
        p[1]["x"], p[1]["y"] = p[0]["x"], p[0]["y"]
        bad.append(p)
        bad += [good[:-1], None, []]
        for p in bad:
            with self.subTest(p=p), self.assertRaises(InputError):
                validate_placements(self.g, self.inv, p)
        short = inventory([(16, 8, 3)])
        with self.assertRaisesRegex(InputError, "inventory"):
            validate_placements(self.g, short, good)
        changed = copy.deepcopy(self.g)
        changed["colors"].append({"id": 2, "name": "Red", "rgb": [255, 0, 0]})
        changed["grid"][0][0] = 2
        with self.assertRaisesRegex(InputError, "color"):
            validate_placements(changed, self.inv, good)

    def test_malformed_grid_inventory_and_limits(self):
        bad_grids = [None, [], {}, {**self.g, "schema_version": True}, {**self.g, "schema_version": 2},
                     {**self.g, "width": True}, {**self.g, "height": 0}, {**self.g, "width": 65},
                     grid([[1] * 17 for _ in range(16)]), {**self.g, "grid": [[1]]},
                     {**self.g, "grid": [[True] * 4 for _ in range(4)]}, {**self.g, "colors": []}]
        for field, value in (("id", True), ("name", " "), ("rgb", [True, 0, 0])):
            c = copy.deepcopy(self.g)
            c["colors"][0][field] = value
            bad_grids.append(c)
        for g in bad_grids:
            with self.subTest(grid=g), self.assertRaises(InputError):
                normalize_grid(g)
        bad_inv = [None, [], {}, {**self.inv, "schema_version": True}, {**self.inv, "extra": 1},
                   {**self.inv, "pieces": []}, {**self.inv, "pieces": self.inv["pieces"] * 2}]
        for key, value in (("color_id", True), ("color_id", 2), ("shape", []), ("shape", "2x1"),
                           ("available", -1), ("available", 1.0), ("available", 1_000_000_001),
                           ("rotate", 1), ("rotate", True)):
            i = copy.deepcopy(self.inv)
            i["pieces"][0][key] = value
            bad_inv.append(i)
        for i in bad_inv:
            with self.subTest(inventory=i), self.assertRaises(InputError):
                normalize_inventory(i, self.g)
        for settings in ((float("nan"), 10, 8), (float("inf"), 10, 8), (-1, 0, 8), (301, 10, 8),
                         (True, 1, 8), (1, True, 8), (1, -1, 8), (1, 2_000_001, 8), (1, 1, 9)):
            with self.subTest(settings=settings), self.assertRaises(InputError):
                validate_settings(*settings)
        for content in (b'{"a":1,"a":2}', b'\xff', b'[' * 2000, b' ' * (256 * 1024 + 1)):
            self.gpath.write_bytes(content)
            with self.assertRaises(InputError):
                read_json(self.gpath)

    def test_complete_bundle_crossings_and_tampering(self):
        out = self.root / "packed"
        result = pack(self.gpath, self.ipath, out, section_size=3)
        self.assertEqual(result["status"], "optimal")
        self.assertEqual(check(out, self.gpath, self.ipath)["crossing_pieces"], 3)
        p = json.loads((out / "placements.json").read_text())
        validate_plan(p, self.g, self.inv)
        html = (out / "instructions.html").read_text()
        (out / "instructions.html").write_text(html.replace('<span>P1</span>', '<span>P2</span>', 1))
        with self.assertRaises(AssertionError):
            check(out, self.gpath, self.ipath)
        (out / "instructions.html").write_text(html.replace('<td>0°</td>', '<td>90°</td>', 1))
        with self.assertRaises(AssertionError):
            check(out, self.gpath, self.ipath)

    def test_atomic_failure_invalid_solver_and_no_solution_artifacts(self):
        out = self.root / "packed"
        with patch('mosaic_parts.packing_export.solve', side_effect=SolverError("injected failure")):
            with self.assertRaises(SolverError):
                pack(self.gpath, self.ipath, out)
        self.assertFalse(out.exists())
        broken = solve(self.g, self.inv)
        broken["placements"][0]["x"] = 999
        with patch('mosaic_parts.packing_export.solve', return_value=broken):
            with self.assertRaises(InputError):
                pack(self.gpath, self.ipath, out)
        self.assertFalse(out.exists())
        with patch('mosaic_parts.packing_solver._candidates', side_effect=RuntimeError('injected')):
            with self.assertRaises(SolverError):
                solve(self.g, self.inv)
        with patch('mosaic_parts.packing_export.instructions', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                pack(self.gpath, self.ipath, out)
        self.assertFalse(out.exists())
        self.assertEqual(list(self.root.glob('.packed-*')), [])
        pack(self.gpath, self.ipath, out, time_limit=0)
        self.assertEqual([p.name for p in out.iterdir()], ['solve.json'])
        with self.assertRaises(InputError):
            pack(self.gpath, self.ipath, out)
        self.inv = inventory([(0, 0, 0)])
        self.inputs()
        pack(self.gpath, self.ipath, self.root / 'impossible')
        self.assertEqual([p.name for p in (self.root / 'impossible').iterdir()], ['solve.json'])

    def test_cli_status_codes_and_repeatable_artifacts(self):
        for name, options, code in [('a', [], 0), ('b', [], 0), ('unknown', ['--time-limit', '0'], 4),
                                    ('bad', ['--time-limit', 'nan'], 2), ('limited', ['--node-limit', '0'], 0)]:
            env = {**os.environ, 'PYTHONHASHSEED': '1' if name == 'a' else '9876'}
            command = [sys.executable, '-m', 'mosaic_parts', 'pack', str(self.gpath), '--inventory',
                       str(self.ipath), '--output', str(self.root / name), *options]
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertNotIn('Traceback', result.stderr)
        for p in (self.root / 'a').iterdir():
            self.assertEqual(p.read_bytes(), (self.root / 'b' / p.name).read_bytes())
        self.inv = inventory([(0, 0, 0)])
        self.inputs()
        result = subprocess.run([sys.executable, '-m', 'mosaic_parts', 'pack', str(self.gpath), '--inventory',
                                 str(self.ipath), '--output', str(self.root / 'infeasible')], capture_output=True)
        self.assertEqual(result.returncode, 3)

    def test_max_cells_skinny_and_escaped_color_name(self):
        self.g = grid([[1] * 64 for _ in range(4)])
        self.g['colors'][0]['name'] = '= <script>alert("x")</script>'
        self.inv = inventory([(256, 128, 64)])
        self.inputs()
        out = self.root / 'wide'
        self.assertEqual(pack(self.gpath, self.ipath, out)['piece_count'], 64)
        self.assertEqual(check(out, self.gpath, self.ipath)['cells'], 256)


if __name__ == '__main__':
    unittest.main()
