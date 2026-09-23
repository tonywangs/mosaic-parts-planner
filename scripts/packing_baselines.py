"""Simple inventory-aware baselines, independent of optimizer candidate masks."""


def baseline(g, inv, *, only_units=False):
    width, height = g['width'], g['height']
    stock = sorted(inv['pieces'], key=lambda p: (p['color_id'], p['shape']))
    left = [p['available'] for p in stock]
    covered, placements = set(), []
    for y in range(height):
        for x in range(width):
            if (y, x) in covered:
                continue
            options = []
            for i, p in enumerate(stock):
                if p['color_id'] != g['grid'][y][x] or not left[i] or (only_units and p['shape'] != '1x1'):
                    continue
                w, h = map(int, p['shape'].split('x'))
                dims = [(w, h, 0)]
                if p['rotate']:
                    dims.append((h, w, 90))
                for a, b, angle in dims:
                    coords = {(yy, xx) for yy in range(y, y + b) for xx in range(x, x + a)}
                    if (x + a <= width and y + b <= height and not covered.intersection(coords)
                            and all(g['grid'][yy][xx] == p['color_id'] for yy, xx in coords)):
                        options.append((-a * b, i, angle, a, b, coords))
            if not options:
                return None
            _, i, angle, a, b, coords = min(options, key=lambda v: v[:3])
            left[i] -= 1
            covered.update(coords)
            placements.append({'id': len(placements) + 1, 'color_id': stock[i]['color_id'],
                               'shape': stock[i]['shape'], 'x': x, 'y': y,
                               'width': a, 'height': b, 'rotation': angle})
    return placements
