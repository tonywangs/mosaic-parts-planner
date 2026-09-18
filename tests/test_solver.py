from collections import Counter
from itertools import product
import random
import unittest

from mosaic_parts.model import Color, InputError
from mosaic_parts.solver import assign


def objective(pixels, colors, placement):
    return sum(sum((p[c] - colors[j].rgb[c]) ** 2 for c in range(3))
               for p, j in zip(pixels, placement))


class SolverTests(unittest.TestCase):
    def assert_optimal(self, pixels, colors):
        actual = assign(pixels, colors)
        candidates = []
        for placement in product(range(len(colors)), repeat=len(pixels)):
            counts = Counter(placement)
            if all(counts[j] <= color.available for j, color in enumerate(colors)):
                candidates.append(objective(pixels, colors, placement))
        self.assertTrue(candidates)
        self.assertEqual(len(actual), len(pixels))
        counts = Counter(actual)
        self.assertTrue(all(counts[j] <= c.available for j, c in enumerate(colors)))
        self.assertEqual(objective(pixels, colors, actual), min(candidates))
        self.assertEqual(actual, assign(pixels, colors))

    def test_exhaustive_binary_colors_all_small_inputs(self):
        # Every input of lengths 1..4 over three grayscale values, every
        # sufficient capacity vector including zero stock and excess stock.
        for n in range(1, 5):
            for values in product((0, 1, 2), repeat=n):
                for capacities in product(range(n + 1), repeat=2):
                    if sum(capacities) < n:
                        continue
                    colors = [Color("a", (0, 0, 0), capacities[0]),
                              Color("b", (2, 2, 2), capacities[1])]
                    self.assert_optimal([(v, v, v) for v in values], colors)

    def test_seeded_three_color_cases(self):
        rng = random.Random(9771)
        for _ in range(100):
            n = rng.randint(1, 6)
            capacities = [rng.randrange(n + 1) for _ in range(3)]
            capacities[0] += max(0, n - sum(capacities))
            colors = [Color(str(j), tuple(rng.randrange(256) for _ in range(3)), capacities[j])
                      for j in range(3)]
            pixels = [tuple(rng.randrange(256) for _ in range(3)) for _ in range(n)]
            self.assert_optimal(pixels, colors)

    def test_reassignment_beats_greedy(self):
        colors = [Color("black", (0, 0, 0), 1), Color("white", (255, 255, 255), 1)]
        self.assertEqual(assign([(100, 100, 100), (0, 0, 0)], colors), [1, 0])

    def test_duplicate_rgb_names_and_zero_capacity(self):
        self.assert_optimal([(1, 2, 3)] * 4,
                            [Color("a", (1, 2, 3), 0), Color("b", (1, 2, 3), 2), Color("c", (1, 2, 3), 9)])

    def test_insufficient(self):
        with self.assertRaisesRegex(InputError, "need 2 tiles, have 1"):
            assign([(0, 0, 0)] * 2, [Color("a", (0, 0, 0), 1)])
