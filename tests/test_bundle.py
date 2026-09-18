import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mosaic_parts.example import make_example
from mosaic_parts.export import convert
from mosaic_parts.model import InputError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_bundle", ROOT / "scripts" / "check_bundle.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        make_example(self.root / "input")
        self.image = self.root / "input" / "source.png"
        self.inventory = self.root / "input" / "inventory.json"

    def build(self, name="plan", width=24, height=16, **kwargs):
        dest = self.root / name
        convert(self.image, self.inventory, dest, width, height, **kwargs)
        return dest

    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, "-m", "mosaic_parts", *map(str, args)],
                              capture_output=True, text=True, env=env, cwd=self.root)

    def test_full_example_independent_reconstruction_and_reproducibility(self):
        first, second = self.build("first"), self.build("second")
        self.assertEqual(checker.check(first, self.inventory)["cells"], 384)
        self.assertEqual(sorted(p.name for p in first.iterdir()),
                         ["comparison.json", "instructions.html", "parts.csv", "placements.json", "preview.png", "target.png"])
        for artifact in first.iterdir():
            self.assertEqual(artifact.read_bytes(), (second / artifact.name).read_bytes(), artifact.name)
        result = json.loads((first / "comparison.json").read_text())
        self.assertEqual(result["constrained"]["excess_tiles"], 0)
        self.assertGreater(result["nearest_unconstrained"]["excess_tiles"], 0)
        self.assertGreater(result["constrained"]["total_squared_rgb_error"],
                           result["nearest_unconstrained"]["total_squared_rgb_error"])

    def test_partial_sections_and_all_zero_stock_colors(self):
        data = json.loads(self.inventory.read_text())
        data["colors"].append({"name": "Unused", "rgb": [0, 0, 0], "available": 0})
        self.inventory.write_text(json.dumps(data))
        plan = self.build(width=13, height=9, section_size=5)
        self.assertEqual(checker.check(plan, self.inventory)["sections"], 6)

    def test_single_cell_and_long_skinny_grids(self):
        for w, h in ((1, 1), (1, 128), (128, 1)):
            plan = self.build(f"plan-{w}-{h}", width=w, height=h, section_size=16)
            checker.check(plan, self.inventory)

    def test_escaped_names_and_spreadsheet_formulas(self):
        data = json.loads(self.inventory.read_text())
        data["colors"][0]["name"] = '<script>alert("x")</script> & café'
        data["colors"][1]["name"] = '=HYPERLINK("http://example.invalid")'
        self.inventory.write_text(json.dumps(data))
        plan = self.build()
        checker.check(plan, self.inventory)
        html = (plan / "instructions.html").read_text()
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_checker_detects_visible_cell_and_total_tampering(self):
        plan = self.build()
        path = plan / "instructions.html"
        original = path.read_text()
        path.write_text(original.replace('<span>1</span>', '<span>2</span>', 1))
        with self.assertRaises(AssertionError):
            checker.check(plan, self.inventory)
        path.write_text(original.replace('<th>Count</th>', '<th>Wrong</th>', 1))
        with self.assertRaises(AssertionError):
            checker.check(plan, self.inventory)

    def test_existing_output_and_atomic_failure(self):
        plan = self.build()
        original = (plan / "placements.json").read_bytes()
        with self.assertRaisesRegex(InputError, "already exists"):
            self.build()
        self.assertEqual((plan / "placements.json").read_bytes(), original)
        with patch("mosaic_parts.export.instructions", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.build("failed")
        self.assertFalse((self.root / "failed").exists())
        self.assertEqual(list(self.root.glob(".failed-*")), [])

    def test_cli_invalid_inputs_actionable_without_traceback(self):
        base = ["convert", self.image, "--inventory", self.inventory, "--output", self.root / "out",
                "--width", "24", "--height", "16"]
        for extra, message in ((["--width", "0"], "width"), (["--height", "128"], "maximum"),
                               (["--section-size", "17"], "section"), (["--background", "white"], "hex"),
                               (["--inventory", self.root / "missing.json"], "No such file")):
            result = self.cli(*base, *extra)
            self.assertEqual(result.returncode, 2)
            self.assertIn(message, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((self.root / "out").exists())
        self.inventory.write_text('{"colors":[{"name":"x","rgb":[0,0,0],"available":0}]}')
        result = self.cli(*base)
        self.assertEqual(result.returncode, 2)
        self.assertIn("need 384 tiles, have 0", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_reproducible_across_hash_seeds(self):
        for seed in ("1", "777"):
            result = self.cli("convert", self.image, "--inventory", self.inventory, "--output", self.root / seed,
                              "--width", 12, "--height", 8, env={**os.environ, "PYTHONHASHSEED": seed})
            self.assertEqual(result.returncode, 0, result.stderr)
        for path in (self.root / "1").iterdir():
            self.assertEqual(path.read_bytes(), (self.root / "777" / path.name).read_bytes())
