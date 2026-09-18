#!/usr/bin/env python3
"""Optional Chromium screen/PDF checks. See requirements-print.txt."""

import argparse
import json
from pathlib import Path
import re
import tempfile

from PIL import Image
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from mosaic_parts.example import make_example
from mosaic_parts.export import convert, write_json
from check_bundle import check


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="new directory for PDFs and screenshots; temporary by default")
    args = parser.parse_args(argv)
    if args.output is None:
        with tempfile.TemporaryDirectory(prefix="mosaic-print-artifacts-") as temp:
            main(["--output", str(Path(temp) / "artifacts")])
        return
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()
    results = []
    with tempfile.TemporaryDirectory(prefix="mosaic-print-") as temp, sync_playwright() as playwright:
        root = Path(temp)
        make_example(root / "example")
        convert(root / "example/source.png", root / "example/inventory.json", root / "example-plan", 24, 16)
        # A dense section exercising all 32 colors and maximum section dimensions.
        palette = [(i * 7, 255 - i * 6, i * 3) for i in range(32)]
        image = Image.new("RGB", (16, 16))
        image.putdata([palette[i % 32] for i in range(256)])
        image.save(root / "dense.png")
        write_json(root / "dense.json", {"colors": [
            {"name": f"Illustrative color {i + 1}", "rgb": list(rgb), "available": 8}
            for i, rgb in enumerate(palette)]})
        convert(root / "dense.png", root / "dense.json", root / "dense-plan", 16, 16, section_size=16)
        check(root / "dense-plan", root / "dense.json")
        browser = playwright.chromium.launch()
        for case, sections in (("example", 6), ("dense", 1)):
            page = browser.new_page(viewport={"width": 900, "height": 1000})
            requests, errors = [], []
            page.on("request", lambda request: requests.append(request.url))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto((root / (case + "-plan") / "instructions.html").as_uri())
            assert not errors
            assert all(url.startswith(("file:", "data:")) for url in requests)
            page.screenshot(path=str(output / f"{case}-overview.png"))
            page.locator(".sheet").first.screenshot(path=str(output / f"{case}-section.png"))
            page.emulate_media(media="print")
            for paper in ("A4", "Letter"):
                path = output / f"{case}-{paper}.pdf"
                page.pdf(path=str(path), format=paper, print_background=False, prefer_css_page_size=False)
                pdf = PdfReader(path)
                texts = [p.extract_text() for p in pdf.pages]
                found = []
                for index, text in enumerate(texts):
                    ids = list(map(int, re.findall(r"Section (\d+)\b", text)))
                    if ids:
                        assert len(ids) == 1, "multiple sections share a printed page"
                        assert "Section parts" in text, "section totals split from its grid"
                        found.extend(ids)
                assert found == list(range(1, sections + 1)), "printed section missing or duplicated"
                assert sum("Section parts" in text for text in texts) == sections
                assert len(texts) <= sections + 2, "unexpected overflow pages"
                results.append({"case": case, "paper": paper, "pages": len(texts),
                                "sections": sections, "section_totals_on_same_page": True,
                                "external_requests": 0, "browser_errors": 0})
            page.close()
        browser.close()
    write_json(output / "checks.json", results)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
