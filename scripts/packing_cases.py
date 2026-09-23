"""Synthetic packing fixtures and an independent exhaustive tiny-case oracle.

The oracle builds sets of coordinate pairs, tries every covering rectangle,
uses no solver masks/bounds/candidates, and enumerates all complete tilings.
"""

import random

SEED = 230923


def grid(rows):
    colors = max(max(row) for row in rows)
    return {"schema_version": 1, "width": len(rows[0]), "height": len(rows), "grid": rows,
            "colors": [{"id": c, "name": f"Sample {c}", "rgb": [25 * c, 40 * c, 60 * c]}
                       for c in range(1, colors + 1)]}


def inventory(counts, rotate=True):
    return {"schema_version": 1, "pieces": [
        {"color_id": c, "shape": s, "available": n, "rotate": rotate if s == "1x2" else False}
        for c, ns in enumerate(counts, 1) for s, n in zip(("1x1", "1x2", "2x2"), ns)]}


def named_cases():
    return [
        ("rotation_required", grid([[1, 1]]), inventory([(0, 1, 0)], True)),
        ("rotation_forbidden", grid([[1, 1]]), inventory([(0, 1, 0)], False)),
        ("multiple_optima", grid([[1, 1], [1, 1]]), inventory([(0, 2, 0)])),
        ("disconnected_colors", grid([[1, 2, 1], [1, 2, 1]]), inventory([(0, 2, 0), (0, 1, 0)])),
        ("enough_area_no_tiling", grid([[1, 2], [2, 1]]), inventory([(0, 1, 0), (0, 1, 0)])),
        ("scarce_square", grid([[1] * 4 for _ in range(3)]), inventory([(2, 3, 1)])),
        ("greedy_trap", grid([[2, 1, 1, 2], [1, 1, 2, 2]]), inventory([(1, 5, 3), (4, 4, 3)])),
        ("empty_stock", grid([[1]]), inventory([(0, 0, 0)])),
    ]


def tiny_cases(count=300):
    cases = named_cases()
    rng = random.Random(SEED)
    for i in range(count):
        w, h = rng.randint(1, 4), rng.randint(1, 3)
        mode = i % 4
        rows = [[1 if mode == 0 else (1 + ((x + y) % 2) if mode == 1 else rng.randint(1, 2))
                 for x in range(w)] for y in range(h)]
        g = grid(rows)
        ns = [(rng.randrange(w * h + 1), rng.randrange(w * h // 2 + 2), rng.randrange(w * h // 4 + 2))
              for _ in g["colors"]]
        cases.append((f"seed-{SEED}-{i}", g, inventory(ns, i % 3 != 0)))
    return cases


def exhaustive(g, inv):
    if g["width"] * g["height"] > 12:
        raise ValueError("oracle is limited to 12 cells")
    remaining = {(y, x) for y in range(g["height"]) for x in range(g["width"])}
    stock = inv["pieces"]
    left = [p["available"] for p in stock]
    rectangles = []
    for j, p in enumerate(stock):
        a, b = map(int, p["shape"].split("x"))
        sizes = [(a, b)]
        if p["rotate"]:
            sizes.append((b, a))
        for w, h in sizes:
            for y in range(g["height"] - h + 1):
                for x in range(g["width"] - w + 1):
                    cells = {(yy, xx) for yy in range(y, y + h) for xx in range(x, x + w)}
                    if all(g["grid"][yy][xx] == p["color_id"] for yy, xx in cells):
                        rectangles.append((j, cells))
    best, optima, complete = None, 0, 0

    def visit(empty, count):
        nonlocal best, optima, complete
        if not empty:
            complete += 1
            if best is None or count < best:
                best, optima = count, 1
            elif count == best:
                optima += 1
            return
        first = min(empty)
        for j, cells in rectangles:
            if left[j] and first in cells and cells <= empty:
                left[j] -= 1
                visit(empty - cells, count + 1)
                left[j] += 1
    visit(remaining, 0)
    return {"piece_count": best, "optimal_tilings": optima, "complete_tilings": complete}


def benchmark_cases():
    cases = named_cases()
    cases.extend([
        ("solid_16x16", grid([[1] * 16 for _ in range(16)]), inventory([(256, 128, 64)])),
        ("stripes_16x16", grid([[1 + x % 2 for x in range(16)] for _ in range(16)]),
         inventory([(128, 64, 32)] * 2)),
        ("checker_16x16", grid([[1 + (x + y) % 2 for x in range(16)] for y in range(16)]),
         inventory([(128, 64, 32)] * 2)),
    ])
    cases.append(("greedy_suboptimal", grid([[1, 1, 1, 1], [2, 1, 1, 2]]),
                  inventory([(8, 4, 3), (2, 1, 3)])))
    rng = random.Random(SEED)
    for n, counts in (("random_scarce", [(40, 20, 5)] * 2),
                      ("random_abundant", [(100, 50, 25)] * 2)):
        rng.seed(SEED)
        cases.append((n, grid([[rng.randint(1, 2) for _ in range(10)] for _ in range(10)]), inventory(counts)))
    return cases
