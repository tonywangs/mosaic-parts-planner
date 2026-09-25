#!/usr/bin/env python3
"""Check exported joint JSON, CSV, and visible HTML against supplied inputs."""
import argparse
import base64
from collections import Counter
import csv
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from PIL import Image

from mosaic_parts.export import spreadsheet_name
from mosaic_parts.joint_inputs import inputs
from mosaic_parts.joint_validate import validate_plan


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.table = None
        self.row = None
        self.cell = None
        self.tables = {}
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table':
            self.table = attrs.get('class')
        elif tag == 'tr':
            self.row = []
        elif tag in ('td', 'th'):
            self.cell = ''

    def handle_data(self, data):
        self.text.append(data)
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell = None
        elif tag == 'tr' and self.table:
            self.tables.setdefault(self.table, []).append(self.row)
        elif tag == 'table':
            self.table = None


def check(bundle, problem, inventory):
    bundle = Path(bundle)
    p, inv = inputs(problem, inventory)
    plan = json.loads((bundle / 'placements.json').read_text())
    checked = validate_plan(plan, p, inv)
    report = json.loads((bundle / 'solve.json').read_text())
    for key in ('result', 'settings', 'problem', 'inventory', 'generator', 'source'):
        assert report[key] == plan[key], key
    with (bundle / 'parts.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(inv['pieces'])
    for row, item in zip(rows, inv['pieces']):
        used = checked['used'][item['color_id'], item['shape']]
        assert row == dict(zip(('color_id', 'name', 'shape', 'rotate', 'available', 'used', 'remaining'),
                              map(str, (item['color_id'], spreadsheet_name(p['colors'][item['color_id']-1]['name']),
                                        item['shape'], str(item['rotate']).lower(), item['available'], used, item['available']-used))))
    html = Tables()
    html.feed((bundle / 'instructions.html').read_text())
    text = ' '.join(html.text)
    assert f"requested budget: " in text
    assert str(p['error_budget']) in text and str(checked['image_error']) in text
    assert plan['result']['status'] in text
    cells = Counter(cell for row in html.tables['grid'] for cell in row if cell.startswith('P') and cell[1:].isdigit())
    assert cells == Counter({f"P{p['id']}": p['width']*p['height'] for p in plan['placements']})
    reconstructed, labels = {}, {}
    for piece in plan['placements']:
        for y in range(piece['y'], piece['y']+piece['height']):
            for x in range(piece['x'], piece['x']+piece['width']):
                labels[y+1, x+1] = f"P{piece['id']}"
    columns = None
    for row in html.tables['grid']:
        if row[0] == 'Row / Col':
            columns = list(map(int, row[1:]))
        else:
            assert columns is not None and len(row) == len(columns)+1
            for x, label in zip(columns, row[1:]):
                key = (int(row[0]), x)
                assert key not in reconstructed
                reconstructed[key] = label
    assert reconstructed == labels, 'visible instruction coordinates differ from placements'
    listed = [row for row in html.tables['placements'] if row[0].startswith('P') and row[0][1:].isdigit()]
    assert len(listed) == len(plan['placements'])
    by_id = {row[0]: row for row in listed}
    for piece in plan['placements']:
        row = by_id[f"P{piece['id']}"]
        assert row[1:6] == [str(piece['color_id']), piece['shape'], f"{piece['rotation']}°",
                            f"{piece['y']+1}–{piece['y']+piece['height']}",
                            f"{piece['x']+1}–{piece['x']+piece['width']}"]
    for i in checked['recolored_cells']:
        assert f"R{i//p['width']+1} C{i%p['width']+1}" in text
    source_html = (bundle / 'instructions.html').read_text()
    assert '<script' not in source_html
    embedded = re.findall(r'src="data:image/png;base64,([A-Za-z0-9+/=]+)"', source_html)
    assert len(embedded) == 1 and base64.b64decode(embedded[0]) == (bundle / 'preview.png').read_bytes()
    with Image.open(bundle / 'preview.png') as picture:
        w, h = p['width'], p['height']
        assert picture.size == (w*48+24, h*24+32)
        for i, rgb in enumerate(p['pixels']):
            x, y = i % w, i // w
            assert picture.getpixel((x*24+12, y*24+44)) == tuple(rgb)
            color = checked['grid']['grid'][y][x]
            assert picture.getpixel((w*24+24+x*24+4, y*24+36)) == tuple(p['colors'][color-1]['rgb'])
    assert all(path.stat().st_size <= 10*1024**2 for path in bundle.iterdir())
    return {k: checked[k] for k in ('piece_count', 'image_error', 'recolored_cells')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('problem', type=Path)
    parser.add_argument('inventory', type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.bundle, json.loads(args.problem.read_text()), json.loads(args.inventory.read_text())), indent=2))


if __name__ == '__main__':
    main()
