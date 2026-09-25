#!/usr/bin/env python3
"""Exercise self-contained joint assembly instructions in network-blocked Chromium."""
import argparse
import json
from pathlib import Path
import re
import tempfile

from playwright.sync_api import sync_playwright
from pypdf import PdfReader
from mosaic_parts.joint_export import export, load_problem
from check_joint import check
from joint_cases import inventory, problem

ROOT = Path(__file__).resolve().parents[1]


def run():
    sample, _ = load_problem(ROOT/'examples/source.png', ROOT/'examples/joint-palette.json', 6, 4, 200000)
    dense = problem(8, 8, [(i*30,)*3 for i in range(8)]*8, 12484800, [(i*30,)*3 for i in range(8)])
    for c in dense['colors']:
        c['name'] = f"Color {c['id']} <&> " + 'x'*60
    cases = [('sample', sample, json.loads((ROOT/'examples/pieces.json').read_text()), 3),
             ('max_cells_colors_recoloring', dense, inventory([(64, 32, 16)]*8), 3),
             ('skinny', problem(1, 64, [(0, 0, 0)]*64, 0), inventory([(0, 32, 0), (0, 0, 0)]), 8)]
    results = []
    with tempfile.TemporaryDirectory(prefix='joint-print-') as temp, sync_playwright() as playwright:
        root = Path(temp)
        browser = playwright.chromium.launch()
        context = browser.new_context(offline=True)
        requests = []
        context.route('**/*', lambda route: route.abort() if route.request.url.startswith(('http:', 'https:')) else route.continue_())
        for name, p, inv, section in cases:
            bundle = root/name
            export(p, inv, bundle, section_size=section)
            checked = check(bundle, p, inv)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.url))
            page.goto((bundle/'instructions.html').as_uri())
            assert not errors
            assert all(url.startswith(('file:', 'data:')) for url in requests)
            assert page.locator('.joint-summary').count() == 1
            assert page.locator('.placements tbody tr').count() == checked['piece_count']
            page.locator('.diagram').last.scroll_into_view_if_needed()
            assert page.locator('img').evaluate_all('(imgs) => imgs.every(i => i.complete && i.naturalWidth > 0)')
            sheets = page.locator('.sheet h2').all_text_contents()
            page.emulate_media(media='print')
            page.set_viewport_size({'width': 680, 'height': 1000})
            assert page.locator('table').evaluate_all('(ts) => ts.every(t => t.scrollWidth <= 680)')
            for paper in ('A4', 'Letter'):
                target = root/f'{name}-{paper}.pdf'
                page.pdf(path=str(target), format=paper, print_background=False)
                pdf = PdfReader(target)
                found = []
                for pdf_page in pdf.pages:
                    text = pdf_page.extract_text()
                    titles = re.findall(r'Section \d+ — (?:diagram|placement list \d+)', text)
                    if titles:
                        assert len(titles) == 1
                        found.extend(titles)
                        assert ('Continuations owned elsewhere:' if '— diagram' in titles[0] else 'End of placement list.') in text
                assert found == sheets
                results.append({'case': name, 'paper': paper, 'pages': len(pdf.pages), 'instruction_sheets': len(sheets),
                                'all_sheets_intact': True, 'external_requests': 0, 'browser_errors': len(errors), 'checked': checked})
            page.close()
        version = browser.version
        browser.close()
    return {'schema_version': 1, 'chromium': version, 'network': 'offline browser context and HTTP(S) routes aborted',
            'results': results, 'limitation': 'No physical printing or assembly validation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--record', type=Path)
    action.add_argument('--check', type=Path)
    args = parser.parse_args()
    result = run()
    if args.record:
        args.record.write_text(json.dumps(result, indent=2)+'\n')
    if args.check:
        assert result == json.loads(args.check.read_text())
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
