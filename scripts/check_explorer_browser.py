#!/usr/bin/env python3
"""Exercise offline selection/downloads and reconstruct downloaded assembly bundles."""
import json
from pathlib import Path
import tempfile
import zipfile

from playwright.sync_api import sync_playwright
from pypdf import PdfReader
from mosaic_parts.explorer import explore, LABELS
from mosaic_parts.explorer_export import export_comparison, explore_image, read_report
from check_joint import check
from joint_cases import named_cases, problem, inventory

ROOT = Path(__file__).resolve().parents[1]


def run():
    results = []
    with tempfile.TemporaryDirectory(prefix='explorer-browser-') as temp, sync_playwright() as pw:
        root = Path(temp)
        browser = pw.chromium.launch()
        context = browser.new_context(accept_downloads=True, offline=True)
        attempted, errors = [], []
        def block(route):
            if route.request.url.startswith(('http:', 'https:')):
                attempted.append(route.request.url)
                route.abort()
            else:
                route.continue_()
        context.route('**/*', block)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        _, p, inv = named_cases()[1]
        dense = problem(8, 8, [(i*30,)*3 for i in range(8)]*8, 0, [(i*30,)*3 for i in range(8)])
        dense['colors'][0]['name'] = '</script><img onerror=alert(1)> & sample'
        for name, report in [
            ('boundary', explore(p, inv, [301, 299, 300, 301], section_size=1)),
            ('max', explore(dense, inventory([(64, 32, 16)]*8), [12484800, 0], section_size=3)),
            ('unresolved', explore(p, inv, [300], total_time_limit=0)),
            ('infeasible', explore(p, inventory([(0, 0, 0)]*2), [0, 300]))]:
            out = root/name
            export_comparison(report, out)
            page.goto((out/'comparison.html').as_uri())
            assert page.title() == 'Mosaic budget comparison'
            rows = page.locator('tbody tr')
            assert rows.count() == len(report['outcomes'])
            for i, outcome in enumerate(report['outcomes']):
                assert LABELS[outcome['result']['status']] in rows.nth(i).inner_text()
            for index, entry in enumerate(report['plans']):
                pid, plan = entry['id'], entry['plan']
                selector = page.get_by_label('Choose a validated plan')
                selector.focus()
                selector.press('Home')
                for _ in range(index):
                    selector.press('ArrowDown')
                selector.press('Enter')
                assert selector.input_value() == pid
                assert page.locator('.plan:visible').count() == 1
                assert page.locator('#'+pid).is_visible()
                assert pid in page.get_by_role('status').inner_text()
                with page.expect_download() as event:
                    page.get_by_role('link', name='Download assembly bundle (ZIP)').click()
                target = root/f'{name}-{pid}.zip'
                event.value.save_as(target)
                downloaded = root/f'{name}-{pid}'
                with zipfile.ZipFile(target) as archive:
                    assert set(archive.namelist()) == {'solve.json', 'placements.json', 'preview.png', 'instructions.html', 'parts.csv'}
                    archive.extractall(downloaded)
                checked = check(downloaded, plan['problem'], report['inventory'])
                for link, file in [('Download printable instructions', 'instructions.html'), ('Download parts CSV', 'parts.csv')]:
                    with page.expect_download() as event:
                        page.get_by_role('link', name=link, exact=True).click()
                    target = root/f'{name}-{pid}-{file}'
                    event.value.save_as(target)
                    assert target.read_bytes() == (downloaded/file).read_bytes()
                instructions_page = context.new_page()
                instructions_page.goto((downloaded/'instructions.html').as_uri())
                for paper in ('A4', 'Letter'):
                    pdf = downloaded/f'{paper}.pdf'
                    instructions_page.pdf(path=str(pdf), format=paper, print_background=True)
                    reader = PdfReader(pdf)
                    text = '\n'.join(p.extract_text() or '' for p in reader.pages)
                    assert 'Rectangular mosaic assembly' in text and 'Section 1' in text
                instructions_page.close()
                results.append({'case': name, 'plan': pid, **checked})
            if not report['plans']:
                assert page.locator('select').count() == 0
                assert page.get_by_text('No validated plans were returned.', exact=False).is_visible()
        # Real image sampling and comparison in the browser as well.
        out = root/'sample'
        explore_image(ROOT/'examples/source.png', ROOT/'examples/joint-palette.json', ROOT/'examples/pieces.json',
                      out, 6, 4, [0, 50000, 100000, 200000, 400000], section_size=3)
        sample = read_report(out/'comparison.json')
        page.goto((out/'comparison.html').as_uri())
        assert len(sample['plans']) >= 1
        assert page.get_by_label('Choose a validated plan').is_visible()
        assert not attempted and not errors, (attempted, errors)
        browser.close()
    print(json.dumps({'network_requests': attempted, 'javascript_errors': errors, 'checked_downloads': results,
                      'sample_outcomes': sample['outcomes']}, indent=2))


if __name__ == '__main__':
    run()
