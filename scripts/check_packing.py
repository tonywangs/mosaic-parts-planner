#!/usr/bin/env python3
"""Reconstruct JSON and visible HTML rectangles independently of the package."""

import argparse
import base64
from collections import Counter
import csv
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
from check_bundle import Tables


def check(bundle, grid_path, inventory_path):
    g = json.loads(Path(grid_path).read_text())
    inv = json.loads(Path(inventory_path).read_text())
    bundle = Path(bundle)
    p = json.loads((bundle / "placements.json").read_text())
    assert p["schema_version"] == 2
    w, h = g["width"], g["height"]
    assert p["input_grid"] == {"schema_version": 1, "width": w, "height": h, "grid": g["grid"],
                               "colors": [{k: c[k] for k in ("id", "name", "rgb")} for c in g["colors"]]}
    assert p["inventory"] == {"schema_version": 1, "pieces": sorted(inv["pieces"], key=lambda x: (x["color_id"], x["shape"]))}
    stock = {(v["color_id"], v["shape"]): v for v in inv["pieces"]}
    cells, counts, by_id = {}, Counter(), {}
    for number, v in enumerate(p["placements"], 1):
        assert v["id"] == number and all(type(v[k]) is int for k in ("id", "color_id", "x", "y", "width", "height", "rotation"))
        key = v["color_id"], v["shape"]
        assert key in stock
        dims = tuple(map(int, v["shape"].split("x")))
        assert v["shape"] in ("1x1", "1x2", "2x2")
        if v["rotation"] == 90:
            assert v["shape"] == "1x2" and stock[key]["rotate"] is True
            dims = dims[::-1]
        else:
            assert v["rotation"] == 0
        assert dims == (v["width"], v["height"])
        for y in range(v["y"], v["y"] + v["height"]):
            for x in range(v["x"], v["x"] + v["width"]):
                assert 0 <= y < h and 0 <= x < w and (y, x) not in cells
                assert g["grid"][y][x] == v["color_id"]
                cells[y, x] = number
        by_id[number] = v
        counts[key] += 1
        assert counts[key] <= stock[key]["available"]
    assert len(cells) == w * h
    assert p["result"]["piece_count"] == len(by_id)
    assert p["result"]["status"] in ("optimal", "feasible")
    report = json.loads((bundle / "solve.json").read_text())
    assert report["result"] == p["result"] and report["settings"] == p["settings"]
    parser = Tables()
    parser.feed((bundle / "instructions.html").read_text())
    assert not parser.external and not parser.scripts
    size = p["settings"]["section_size"]
    section_cols = (w + size - 1) // size
    diagrams, listing, parts, palette = {}, {}, [], []
    diagram_number = 0
    for table in parser.tables:
        rows = table["rows"]
        if table["kind"] == "grid":
            diagram_number += 1
            sy, sx = divmod(diagram_number - 1, section_cols)
            columns = list(map(int, rows[0][1:]))
            assert columns == list(range(sx * size + 1, min(w, (sx + 1) * size) + 1))
            assert [int(row[0]) for row in rows[1:]] == list(range(sy * size + 1, min(h, (sy + 1) * size) + 1))
            for row in rows[1:]:
                y = int(row[0]) - 1
                assert len(row) == len(columns) + 1
                for x, value in zip(columns, row[1:]):
                    assert value.startswith("P") and (y, x - 1) not in diagrams
                    diagrams[y, x - 1] = int(value[1:])
        elif table["kind"] == "placements":
            for row in rows[1:]:
                assert len(row) == 8 and row[0].startswith("P")
                number = int(row[0][1:])
                assert number not in listing
                v = by_id[number]
                touched = sorted({(y // size) * section_cols + (x // size) + 1
                                  for y in range(v["y"], v["y"] + v["height"])
                                  for x in range(v["x"], v["x"] + v["width"])})
                assert row == [f'P{number}', str(v["color_id"]), v["shape"], f'{v["rotation"]}°',
                               f'{v["y"] + 1}–{v["y"] + v["height"]}',
                               f'{v["x"] + 1}–{v["x"] + v["width"]}', str(touched[0]), ', '.join(map(str, touched))]
                listing[number] = row
        elif table["kind"] == "parts":
            parts.extend(rows[1:])
        elif table["kind"] == "palette":
            palette.extend(rows[1:])
    assert diagrams == cells and set(listing) == set(by_id)
    assert diagram_number == section_cols * ((h + size - 1) // size)
    assert palette == [[str(c["id"]), c["name"], '#' + ''.join(f'{v:02x}' for v in c["rgb"])] for c in g["colors"]]
    items = sorted(inv["pieces"], key=lambda x: (x["color_id"], x["shape"]))
    assert parts == [[str(v["color_id"]), v["shape"], str(counts[v["color_id"], v["shape"]]),
                      str(v["available"]), str(v["available"] - counts[v["color_id"], v["shape"]])] for v in items if v['available']]
    with (bundle / "parts.csv").open(newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert len(csv_rows) == len(items)
    for row, v in zip(csv_rows, items):
        name = g["colors"][v["color_id"] - 1]["name"]
        if name.startswith(("=", "+", "-", "@")):
            name = "'" + name
        count = counts[v["color_id"], v["shape"]]
        assert row == dict(zip(("color_id", "name", "shape", "rotate", "available", "used", "remaining"),
                               map(str, (v["color_id"], name, v["shape"], str(v["rotate"]).lower(), v["available"], count, v["available"] - count))))
    with Image.open(bundle / "preview.png") as picture:
        assert picture.size == (w * 24, h * 24) and picture.mode == "RGB"
        for (y, x), number in cells.items():
            assert picture.getpixel((x * 24 + 12, y * 24 + 12)) == tuple(g["colors"][by_id[number]["color_id"] - 1]["rgb"])
        for v in by_id.values():
            assert picture.getpixel((v["x"] * 24, v["y"] * 24)) == (0, 0, 0)
            assert picture.getpixel((v["x"] * 24 + 2, v["y"] * 24 + 2)) == (255, 255, 255)
        assert len(parser.images) == 1 and parser.images[0].startswith("data:image/png;base64,")
        with Image.open(BytesIO(base64.b64decode(parser.images[0].split(',', 1)[1], validate=True))) as embedded:
            assert embedded.size == picture.size and embedded.tobytes() == picture.tobytes()
    return {"cells": w * h, "pieces": len(by_id), "sections": diagram_number,
            "crossing_pieces": sum(len({(y // size, x // size) for y in range(v["y"], v["y"] + v["height"])
                                        for x in range(v["x"], v["x"] + v["width"])}) > 1 for v in by_id.values()),
            "reconstruction": "JSON, visible HTML, CSV, preview, original grid and inventory agree"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("grid", type=Path)
    parser.add_argument("inventory", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.bundle, args.grid, args.inventory), indent=2))
