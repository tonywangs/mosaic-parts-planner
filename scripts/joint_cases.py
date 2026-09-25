"""Seeded inputs and independent coordinate-set exhaustive joint oracle."""
import random

SEED = 260925


def problem(w, h, pixels, budget, rgbs=((0, 0, 0), (10, 10, 10))):
    return {'schema_version': 1, 'width': w, 'height': h,
            'colors': [{'id': i, 'name': f'Sample {i}', 'rgb': list(rgb)} for i, rgb in enumerate(rgbs, 1)],
            'pixels': [list(p) for p in pixels], 'error_budget': budget}


def inventory(counts, rotate=True):
    return {'schema_version': 1, 'pieces': [
        {'color_id': i, 'shape': shape, 'available': n, 'rotate': rotate if shape == '1x2' else False}
        for i, ns in enumerate(counts, 1) for shape, n in zip(('1x1', '1x2', '2x2'), ns)]}


def named_cases():
    pair = [(0, 0, 0), (10, 10, 10)]
    return [
        ('boundary_below', problem(2, 1, pair, 299), inventory([(2, 1, 0), (2, 1, 0)])),
        ('boundary_exact', problem(2, 1, pair, 300), inventory([(2, 1, 0), (2, 1, 0)])),
        ('rotation_required', problem(2, 1, pair, 300), inventory([(0, 1, 0), (0, 0, 0)])),
        ('rotation_forbidden', problem(2, 1, pair, 300), inventory([(0, 1, 0), (0, 0, 0)], False)),
        ('scarce_nearest_color', problem(2, 1, pair, 300), inventory([(0, 0, 0), (0, 1, 0)])),
        ('tied_colors_and_tilings', problem(2, 2, [(5, 5, 5)] * 4, 300), inventory([(0, 2, 0), (0, 2, 0)])),
        ('geometry_impossible', problem(3, 1, [(0, 0, 0)] * 3, 0), inventory([(0, 0, 1), (0, 0, 0)])),
        ('empty_inventory', problem(1, 1, [(0, 0, 0)], 300), inventory([(0, 0, 0), (0, 0, 0)])),
    ]


def tiny_cases(count=240):
    cases = named_cases()
    rng = random.Random(SEED)
    for i in range(count):
        w, h = rng.choice(((1, 1), (2, 1), (1, 3), (2, 2), (3, 2)))
        rgbs = [(0, 0, 0), (10, 10, 10), (5, 0, 10)][:2 + i % 2]
        pixels = [rng.choice(rgbs + [(4, 6, 3)]) for _ in range(w*h)]
        ns = [tuple(rng.randrange(4) for _ in range(3)) for _ in rgbs]
        p = problem(w, h, pixels, rng.randrange(0, w*h*300+1), rgbs)
        cases.append((f'seed-{SEED}-{i}', p, inventory(ns, i % 3 != 0)))
    return cases


def exhaustive(p, inv):
    """Enumerate every complete tiling; no production candidates/bounds/masks.

    Branch on the LAST remaining cell and every rectangle containing it.
    Compute full image errors only at leaves, from a separate cell-color map.
    """
    if p['width'] * p['height'] > 6:
        raise ValueError('exhaustive joint oracle limited to six cells')
    empty = {(x, y) for y in range(p['height']) for x in range(p['width'])}
    rectangles = []
    for i, entry in enumerate(inv['pieces']):
        a, b = [int(n) for n in entry['shape'].split('x')]
        for w, h in [(a, b)] + ([(b, a)] if entry['rotate'] else []):
            for y in range(p['height'] - h + 1):
                for x in range(p['width'] - w + 1):
                    cells = {(xx, yy) for yy in range(y, y+h) for xx in range(x, x+w)}
                    rectangles.append((i, entry['color_id'], cells))
    remaining = [e['available'] for e in inv['pieces']]
    best = None
    colored = {}

    def visit(empty, count):
        nonlocal best
        if not empty:
            error = 0
            for (x, y), color in colored.items():
                target = p['pixels'][y*p['width']+x]
                rgb = p['colors'][color-1]['rgb']
                error += sum((a-b)**2 for a, b in zip(target, rgb))
            if error <= p['error_budget'] and (best is None or count < best):
                best = count
            return
        cell = max(empty)
        for i, color, cells in rectangles:
            if remaining[i] and cell in cells and cells <= empty:
                remaining[i] -= 1
                colored.update({cell: color for cell in cells})
                visit(empty - cells, count + 1)
                for cell2 in cells:
                    del colored[cell2]
                remaining[i] += 1
    visit(empty, 0)
    return best
