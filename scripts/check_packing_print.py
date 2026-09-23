#!/usr/bin/env python3
"""Exercise rectangular instructions in Chromium and A4/Letter PDFs."""

import argparse
import json
from pathlib import Path
import re
import tempfile

from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from mosaic_parts.export import convert, write_json
from mosaic_parts.packing_export import pack
from check_packing import check
from packing_cases import grid, inventory

ROOT = Path(__file__).resolve().parents[1]


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    results = []
    with tempfile.TemporaryDirectory(prefix='packing-print-inputs-') as temp, sync_playwright() as playwright:
        root = Path(temp)
        convert(ROOT / 'examples/source.png', ROOT / 'examples/inventory.json', root / 'converted', 6, 4)
        sample = json.loads((root / 'converted/placements.json').read_text())
        dense = grid([[1 + (y * 16 + x) % 32 for x in range(16)] for y in range(16)])
        for c in dense['colors']:
            c['rgb'] = [c['id'] * 7, 255 - c['id'] * 6, c['id'] * 3]
            c['name'] = f"Color {c['id']:02} " + 'x' * 71
        cases = [('image_example', sample, json.loads((ROOT / 'examples/pieces.json').read_text()), 3),
                 ('cross_four_sections', grid([[1] * 4 for _ in range(4)]), inventory([(16, 8, 4)]), 3),
                 ('dense_256_cells', dense, inventory([(8, 0, 0)] * 32), 8)]
        browser = playwright.chromium.launch()
        for name, g, inv, section in cases:
            gpath, ipath, bundle = root / f'{name}-grid.json', root / f'{name}-pieces.json', root / name
            write_json(gpath, g)
            write_json(ipath, inv)
            answer = pack(gpath, ipath, bundle, section_size=section)
            assert answer['status'] == 'optimal'
            checked = check(bundle, gpath, ipath)
            page = browser.new_page(viewport={'width': 1000, 'height': 1000})
            requests, errors = [], []
            page.on('request', lambda request: requests.append(request.url))
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto((bundle / 'instructions.html').as_uri())
            assert not errors and all(url.startswith(('file:', 'data:')) for url in requests)
            assert page.locator('.grid').count() == checked['sections']
            assert page.locator('.placements tbody tr').count() == checked['pieces']
            # Exercise the cross-section navigation target and rendered diagram.
            page.locator('.diagram').last.scroll_into_view_if_needed()
            page.locator('.diagram').last.screenshot(path=str(output / f'{name}-section.png'))
            sheets = page.locator('.sheet h2').all_text_contents()
            page.emulate_media(media='print')
            # Check table content width against the narrower A4 printable area.
            page.set_viewport_size({'width': 680, 'height': 1000})
            assert page.locator('table').evaluate_all('(tables) => tables.every(t => t.scrollWidth <= 680)'), 'table overflow'
            for paper in ('A4', 'Letter'):
                path = output / f'{name}-{paper}.pdf'
                page.pdf(path=str(path), format=paper, print_background=False)
                pdf = PdfReader(path)
                texts = [p.extract_text() for p in pdf.pages]
                found = []
                for text in texts:
                    titles = re.findall(r'Section \d+ — (?:diagram|placement list \d+)', text)
                    if titles:
                        assert len(titles) == 1, 'two instruction sheets share one PDF page'
                        found.extend(titles)
                        if '— diagram' in titles[0]:
                            assert 'Continuations owned elsewhere:' in text, 'diagram split across pages'
                        else:
                            assert 'End of placement list.' in text, 'placement list split across pages'
                assert found == sheets, (name, paper, found, sheets)
                assert len(texts) <= len(sheets) + 5, 'unexpected PDF overflow'
                results.append({'case': name, 'paper': paper, 'pages': len(texts), 'instruction_sheets': len(sheets),
                                'all_sheets_intact': True, 'browser_errors': len(errors), 'external_requests': 0,
                                'independent_check': checked})
            page.close()
        version = browser.version
        browser.close()
    return {'schema_version': 1, 'chromium': version, 'results': results,
            'limitation': 'Browser rendering/PDF checks; no physical printing or human assembly study.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='new directory for screenshots/PDFs, temporary by default')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--record', type=Path)
    action.add_argument('--check', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='packing-print-artifacts-') as temp:
        result = run(args.output or Path(temp) / 'artifacts')
    if args.record:
        write_json(args.record, result)
    if args.check:
        assert result == json.loads(args.check.read_text()), 'browser evidence changed'
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
