#!/usr/bin/env python3
"""Independently reconstruct visible HTML tables, then cross-check all artifacts.

No imports from mosaic_parts. This deliberately does not trust an embedded JSON
copy or HTML data-* attributes to represent what a person would assemble.
"""

import argparse
import base64
from collections import Counter
import csv
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path

from PIL import Image


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.images = []
        self.external = []
        self.scripts = 0

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "script":
            self.scripts += 1
        for key in ("src", "href"):
            if key in attrs and not attrs[key].startswith(("data:", "#")):
                self.external.append(attrs[key])
        if tag == "img":
            self.images.append(attrs.get("src", ""))
        if tag == "table":
            assert self.table is None, "nested tables not supported"
            self.table = {"kind": attrs.get("class"), "rows": []}
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = ""

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table["rows"].append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def check(bundle: Path, inventory_path: Path):
    plan = json.loads((bundle / "placements.json").read_text(encoding="utf-8"))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))["colors"]
    width, height = plan["width"], plan["height"]
    assert plan["schema_version"] == 1
    assert len(plan["grid"]) == height and all(len(row) == width for row in plan["grid"])
    assert len(plan["colors"]) == len(inventory)
    for i, (actual, expected) in enumerate(zip(plan["colors"], inventory), 1):
        assert actual["id"] == i
        assert all(actual[key] == expected[key] for key in ("name", "rgb", "available"))
    parser = Tables()
    html = (bundle / "instructions.html").read_text(encoding="utf-8")
    parser.feed(html)
    assert not parser.external and parser.scripts == 0, "instructions must be self-contained without scripts"
    reconstructed, section_counts = {}, []
    palette_tables = 0
    awaiting_total = False
    section_size = plan["settings"]["section_size"]
    expected_sections = [(top, left) for top in range(0, height, section_size)
                         for left in range(0, width, section_size)]
    for table in parser.tables:
        rows = table["rows"]
        if table["kind"] == "grid":
            assert not awaiting_total, "missing section totals"
            top, left = expected_sections[len(section_counts)]
            assert rows[0][0] == "Row / Col"
            columns = list(map(int, rows[0][1:]))
            assert columns == list(range(left + 1, min(left + section_size, width) + 1))
            assert [int(row[0]) for row in rows[1:]] == list(range(top + 1, min(top + section_size, height) + 1))
            counts = Counter()
            for row in rows[1:]:
                y = int(row[0])
                assert len(row) == len(columns) + 1
                for x, value in zip(columns, row[1:]):
                    number = int(value)
                    assert 1 <= number <= len(inventory)
                    assert 1 <= x <= width and 1 <= y <= height
                    assert (y, x) not in reconstructed, "duplicate HTML coordinate"
                    reconstructed[y, x] = number
                    counts[number] += 1
            section_counts.append(counts)
            awaiting_total = True
        elif table["kind"] == "totals":
            assert awaiting_total
            assert rows[0] == ["Color ID", "Count"] * 4
            assert all(len(row) == 8 for row in rows[1:])
            totals = [(int(row[i]), int(row[i + 1])) for row in rows[1:]
                      for i in range(0, 8, 2) if row[i] or row[i + 1]]
            assert len(totals) == len(dict(totals))
            assert dict(totals) == dict(section_counts[-1]), "section parts disagree with visible grid"
            awaiting_total = False
        elif table["kind"] == "palette":
            palette_tables += 1
            assert len(rows) == len(inventory) + 1
            for number, row in enumerate(rows[1:], 1):
                color = plan["colors"][number - 1]
                assert row == [str(number), color["name"], str(color["rgb"]), str(color["used"]),
                               str(color["available"]), str(color["available"] - color["used"])]
    assert palette_tables == 1 and not awaiting_total
    assert len(section_counts) == len(expected_sections)
    assert len(reconstructed) == width * height
    grid = [[reconstructed[y + 1, x + 1] for x in range(width)] for y in range(height)]
    assert grid == plan["grid"], "visible HTML reconstruction disagrees with placements"
    counts = Counter(reconstructed.values())
    for number, color in enumerate(inventory, 1):
        assert counts[number] <= color["available"], "inventory exceeded"
        assert counts[number] == plan["colors"][number - 1]["used"]
    with (bundle / "parts.csv").open(encoding="utf-8", newline="") as stream:
        parts = list(csv.DictReader(stream))
    assert len(parts) == len(inventory)
    for number, (part, color) in enumerate(zip(parts, inventory), 1):
        name = color["name"]
        if name.startswith(("=", "+", "-", "@")):
            name = "'" + name
        assert part == dict(zip(["color_id", "name", "r", "g", "b", "available", "used", "remaining"],
                                map(str, [number, name, *color["rgb"], color["available"], counts[number],
                                          color["available"] - counts[number]])))
    with Image.open(bundle / "preview.png") as preview:
        assert preview.size == (width * 16, height * 16) and preview.mode == "RGB"
        for y in range(preview.height):
            for x in range(preview.width):
                assert preview.getpixel((x, y)) == tuple(inventory[grid[y // 16][x // 16] - 1]["rgb"])
        assert len(parser.images) == 1 and parser.images[0].startswith("data:image/png;base64,")
        with Image.open(BytesIO(base64.b64decode(parser.images[0].split(",", 1)[1], validate=True))) as embedded:
            assert embedded.size == preview.size and embedded.tobytes() == preview.tobytes()
    comparison = json.loads((bundle / "comparison.json").read_text(encoding="utf-8"))
    with Image.open(bundle / "target.png") as target:
        assert target.size == (width, height) and target.mode == "RGB"
        pixels = list(target.get_flattened_data())
    costs = [[sum((a - b) ** 2 for a, b in zip(p, c["rgb"])) for c in inventory] for p in pixels]
    nearest = [min(range(len(inventory)), key=lambda i: row[i]) + 1 for row in costs]
    assert nearest == comparison["nearest_color_ids"]
    for name, placement in (("constrained", [c for row in grid for c in row]), ("nearest_unconstrained", nearest)):
        used = Counter(placement)
        error = sum(row[number - 1] for row, number in zip(costs, placement))
        excess = [max(0, used[i] - c["available"]) for i, c in enumerate(inventory, 1)]
        assert comparison[name] == {"total_squared_rgb_error": error,
                                  "mean_squared_rgb_error_per_channel": error / (3 * width * height),
                                  "counts": [used[i] for i in range(1, len(inventory) + 1)],
                                  "excess_by_color": excess, "excess_tiles": sum(excess),
                                  "colors_over_inventory": sum(v > 0 for v in excess)}
    assert comparison["constrained"]["total_squared_rgb_error"] >= comparison["nearest_unconstrained"]["total_squared_rgb_error"]
    return {"cells": width * height, "sections": len(section_counts), "inventory_excess": 0,
            "html_reconstruction": "matches placements, preview, parts, and comparison"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("inventory", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.bundle, args.inventory), indent=2))


if __name__ == "__main__":
    main()
