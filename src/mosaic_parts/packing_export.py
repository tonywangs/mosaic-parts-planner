"""Atomic rectangular plan bundles; no assembly artifacts without a valid plan."""

import base64
from collections import Counter
import csv
from html import escape
from io import BytesIO
from pathlib import Path
import platform
import shutil
import tempfile

from PIL import Image, ImageDraw, __version__ as pillow_version

from . import __version__
from .export import hex_rgb, spreadsheet_name, write_json
from .model import InputError
from .packing_inputs import normalize_grid, normalize_inventory, read_json, validate_settings
from .packing_solver import solve
from .packing_validate import validate_plan


def section_ids(p, width, size):
    columns = (width + size - 1) // size
    return [sy * columns + sx + 1
            for sy in range(p["y"] // size, (p["y"] + p["height"] - 1) // size + 1)
            for sx in range(p["x"] // size, (p["x"] + p["width"] - 1) // size + 1)]


def preview(plan):
    grid = plan["input_grid"]
    scale = 24
    picture = Image.new("RGB", (grid["width"] * scale, grid["height"] * scale), "white")
    draw = ImageDraw.Draw(picture)
    for p in plan["placements"]:
        box = (p["x"] * scale, p["y"] * scale,
               (p["x"] + p["width"]) * scale - 1, (p["y"] + p["height"]) * scale - 1)
        draw.rectangle(box, fill=tuple(grid["colors"][p["color_id"] - 1]["rgb"]), outline="black", width=2)
        # White inset makes boundaries visible even on black pieces.
        draw.rectangle((box[0] + 2, box[1] + 2, box[2] - 2, box[3] - 2), outline="white")
    return picture


def instructions(plan, picture):
    grid = plan["input_grid"]
    w, h, size = grid["width"], grid["height"], plan["settings"]["section_size"]
    pieces = plan["placements"]
    cells = {}
    for p in pieces:
        for y in range(p["y"], p["y"] + p["height"]):
            for x in range(p["x"], p["x"] + p["width"]):
                cells[y, x] = p
    buf = BytesIO()
    picture.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           '<title>Rectangular mosaic assembly</title><style>',
           'body{font:14px system-ui,sans-serif;color:#111;margin:24px;line-height:1.35}',
           'table{border-collapse:collapse;margin:10px 0;width:100%}td,th{border:1px solid #777;padding:4px;text-align:center}',
           'tr{break-inside:avoid}.palette td{overflow-wrap:anywhere;max-width:65mm}',
           '.overview{max-width:90mm;max-height:75mm;image-rendering:pixelated}',
           '.sheet{break-before:page}.grid{width:auto;table-layout:fixed}',
           '.grid td{width:10mm;height:10mm;padding:0;font-size:9pt}',
           '.grid th{font-size:9pt}.grid span{background:white;color:black;padding:1px}',
           '.placements{font-size:9pt}.placements td{height:5mm}h1,h2{line-height:1.2}',
           '@page{size:auto;margin:15mm}@media print{body{margin:0;font-size:10pt}',
           '.sheet{break-inside:avoid}.grid{print-color-adjust:exact;-webkit-print-color-adjust:exact}}',
           '</style></head><body><header><h1>Rectangular mosaic assembly</h1>',
           f'<p>{w} columns × {h} rows · {len(pieces)} pieces · solver status: {plan["result"]["status"]}.</p>',
           '<p><strong>Front view, top ↑. Printed rows and columns start at 1.</strong> '
           'Columns increase right, rows down. Do not mirror. JSON x/y start at 0.</p>',
           '<p>Cell labels P1, P2, … identify whole pieces, not colors or placement order. '
           'Repeated labels are cells of the same piece. Solid heavy borders are piece edges; '
           'dashed edges continue into another section. Never cut a piece at a section boundary.</p>',
           '<p>Place each piece exactly once using its owner section’s placement list. The owner contains '
           'its top-left cell. “Touches” lists every section it crosses. Reserve those neighboring cells '
           'and align sections on one continuous backing surface. Each list gives the complete row/column '
           'span, color, and orientation. A 1x2 is width 1, height 2 at 0°; at 90° it is width 2, height 1.</p>',
           '<p>Print at 100% on A4 or Letter. Diagrams are not physical-size templates. Color IDs and piece '
           'labels work without color printing. RGB is illustrative; physical availability and structural '
           'stability are unverified. Backing plates are not included.</p>',
           f'<img class="overview" alt="Front view with rectangular piece boundaries" src="data:image/png;base64,{encoded}">',
           '<h2>Color key</h2><table class="palette"><thead><tr><th>Color ID</th><th>Name</th><th>RGB</th></tr></thead><tbody>']
    for c in grid["colors"]:
        out.append(f'<tr><td>{c["id"]}</td><td>{escape(c["name"])}</td><td>{hex_rgb(c["rgb"])}</td></tr>')
    out.append('</tbody></table><h2>Total parts</h2><p>Zero-stock entries are omitted; all inventory entries are in parts.csv.</p><table class="parts"><thead><tr>'
               '<th>Color ID</th><th>Shape W×H</th><th>Needed</th><th>Available</th><th>Remaining</th>'
               '</tr></thead><tbody>')
    used = Counter((p["color_id"], p["shape"]) for p in pieces)
    for item in plan["inventory"]["pieces"]:
        if item["available"] == 0:
            continue
        count = used[item["color_id"], item["shape"]]
        out.append(f'<tr><td>{item["color_id"]}</td><td>{item["shape"]}</td><td>{count}</td>'
                   f'<td>{item["available"]}</td><td>{item["available"] - count}</td></tr>')
    out.append('</tbody></table></header><main>')
    section = 0
    for top in range(0, h, size):
        for left in range(0, w, size):
            section += 1
            bottom, right = min(h, top + size), min(w, left + size)
            owned = [p for p in pieces if section_ids(p, w, size)[0] == section]
            out.append(f'<section class="sheet diagram" id="section-{section}"><h2>Section {section} — diagram</h2>'
                       f'<p>Rows {top + 1}–{bottom}, columns {left + 1}–{right}. Top ↑; front view.</p>'
                       '<table class="grid"><caption>Piece IDs</caption>'
                       '<thead><tr><th>Row / Col</th>')
            out.extend(f'<th>{x + 1}</th>' for x in range(left, right))
            out.append('</tr></thead><tbody>')
            for y in range(top, bottom):
                out.append(f'<tr><th>{y + 1}</th>')
                for x in range(left, right):
                    p = cells[y, x]
                    edges = {"left": x == p["x"], "right": x == p["x"] + p["width"] - 1,
                             "top": y == p["y"], "bottom": y == p["y"] + p["height"] - 1}
                    cut = {"left": x == left, "right": x == right - 1,
                           "top": y == top, "bottom": y == bottom - 1}
                    borders = ";".join(f'border-{side}:' + ('2px solid black' if edge else
                                        ('2px dashed #555' if cut[side] else '1px dotted #999'))
                                       for side, edge in edges.items())
                    rgb = hex_rgb(grid["colors"][p["color_id"] - 1]["rgb"])
                    out.append(f'<td style="background:{rgb};{borders}"><span>P{p["id"]}</span></td>')
                out.append('</tr>')
            out.append('</tbody></table>')
            visitors = sorted({cells[y, x]["id"] for y in range(top, bottom) for x in range(left, right)
                               if section_ids(cells[y, x], w, size)[0] != section})
            out.append('<p class="continuations">Continuations owned elsewhere: ' +
                       (', '.join(f'P{i} (owner {section_ids(pieces[i - 1], w, size)[0]})' for i in visitors)
                        if visitors else 'none') + '.</p>')
            out.append(f'<p>{len(owned)} pieces owned here. ' +
                       ('Use the following placement list pages; place each listed piece once.' if owned else
                        'No pieces start here. Follow the owner lists referenced above.') + '</p></section>')
            for start in range(0, len(owned), 24):
                out.append(f'<section class="sheet placement-sheet"><h2>Section {section} — placement list {start // 24 + 1}</h2>'
                           '<p>Complete spans, including any cells in neighboring sections. '
                           'Printed coordinates start at 1. Top ↑; front view.</p>'
                           '<table class="placements"><thead><tr><th>Piece</th><th>Color ID</th><th>Shape W×H</th>'
                           '<th>Rotation</th><th>Rows</th><th>Columns</th><th>Owner</th><th>Touches</th></tr></thead><tbody>')
                for p in owned[start:start + 24]:
                    touched = section_ids(p, w, size)
                    out.append(f'<tr><td>P{p["id"]}</td><td>{p["color_id"]}</td><td>{p["shape"]}</td>'
                               f'<td>{p["rotation"]}°</td><td>{p["y"] + 1}–{p["y"] + p["height"]}</td>'
                               f'<td>{p["x"] + 1}–{p["x"] + p["width"]}</td><td>{section}</td>'
                               f'<td>{", ".join(map(str, touched))}</td></tr>')
                out.append('</tbody></table><p>End of placement list.</p></section>')
    out.append('</main></body></html>')
    return '\n'.join(out) + '\n'


def pack(grid_path, inventory_path, output, *, time_limit=10.0, node_limit=100_000, section_size=8):
    validate_settings(time_limit, node_limit, section_size)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise InputError(f"output already exists: {output}; choose a new directory")
    grid = normalize_grid(read_json(grid_path))
    inventory = normalize_inventory(read_json(inventory_path), grid)
    answer = solve(grid, inventory, time_limit=time_limit, node_limit=node_limit)
    result = {key: value for key, value in answer.items() if key != "placements"}
    settings = {"time_limit_seconds": time_limit, "node_limit": node_limit, "section_size": section_size}
    generator = {"name": "mosaic-parts-planner", "version": __version__, "solver": "integer-dfs-v1",
                 "python": platform.python_version(), "pillow": pillow_version}
    report = {"schema_version": 1, "generator": generator, "settings": settings, "result": result}
    plan = None
    if answer["placements"] is not None:
        plan = {"schema_version": 2, "generator": generator, "settings": settings, "result": result,
                "coordinates": "front view; x/y are zero-based; x right, y down; dimensions are width/height",
                "input_grid": grid, "inventory": inventory, "placements": answer["placements"]}
        used = validate_plan(plan, grid, inventory)
    elif answer["status"] not in ("infeasible", "unknown"):
        raise InputError("solver reported a solution without placements")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        write_json(staging / "solve.json", report)
        if plan is not None:
            picture = preview(plan)
            picture.save(staging / "preview.png")
            write_json(staging / "placements.json", plan)
            with (staging / "parts.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(["color_id", "name", "shape", "rotate", "available", "used", "remaining"])
                for p in inventory["pieces"]:
                    count = used[p["color_id"], p["shape"]]
                    writer.writerow([p["color_id"], spreadsheet_name(grid["colors"][p["color_id"] - 1]["name"]),
                                     p["shape"], str(p["rotate"]).lower(), p["available"], count, p["available"] - count])
            (staging / "instructions.html").write_text(instructions(plan, picture), encoding="utf-8")
        if output.exists() or output.is_symlink():
            raise InputError(f"output appeared during packing: {output}; choose a new directory")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return result
