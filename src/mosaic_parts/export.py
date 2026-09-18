"""Deterministic, self-contained export bundle and printable build sheets."""

import base64
from collections import Counter
import csv
from dataclasses import asdict
from html import escape
from io import BytesIO
import json
from pathlib import Path
import tempfile
import shutil

from PIL import Image, __version__ as pillow_version

from . import __version__
from .model import InputError, prepare_image, read_inventory, validate_grid
from .solver import assign, compare


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def spreadsheet_name(name):
    """Avoid spreadsheet formula evaluation while retaining the original in JSON."""
    return "'" + name if name.startswith(("=", "+", "-", "@")) else name


def hex_rgb(rgb):
    return "#" + "".join(f"{v:02x}" for v in rgb)


def instructions(plan, preview):
    width, height = plan["width"], plan["height"]
    size, grid, colors = plan["settings"]["section_size"], plan["grid"], plan["colors"]
    buf = BytesIO()
    preview.save(buf, format="PNG")
    embedded = base64.b64encode(buf.getvalue()).decode("ascii")
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           '<title>Mosaic assembly instructions</title><style>',
           'body{font-family:system-ui,sans-serif;color:#182328;margin:24px;line-height:1.4}',
           'h1,h2{line-height:1.2}table{border-collapse:collapse;margin:12px 0}',
           'th,td{border:1px solid #657178;padding:5px 8px;text-align:center}',
           '.overview{max-width:360px;max-height:360px;image-rendering:pixelated}',
           '.palette td:nth-child(2){max-width:55mm;overflow-wrap:anywhere}',
           '.swatch{display:inline-block;width:18px;height:18px;border:1px solid #333;vertical-align:middle}',
           '.sheet{break-before:page;margin-top:32px}.grid{table-layout:fixed}',
           '.grid td{width:8mm;height:8mm;padding:0;font-size:11pt;font-weight:600}',
           '.grid td span{background:white;color:black;border:1px solid #777;padding:0 2px}',
           '.grid th{font-size:9pt;padding:1mm}.totals{font-size:10pt}',
           '@page{size:auto;margin:15mm}@media print{body{margin:0;font-size:10pt}',
           '.sheet{margin-top:0;break-inside:avoid}.grid{print-color-adjust:exact;',
           '-webkit-print-color-adjust:exact}.overview{max-width:70mm;max-height:70mm}}',
           '</style></head><body><header><h1>Mosaic assembly plan</h1>',
           f'<p>{width} columns × {height} rows · {width * height} single-layer 1×1 tiles.</p>',
           '<p><strong>Front view. Top-left is row 1, column 1.</strong> Columns increase to the right;',
           ' rows increase downward. Do not mirror the plan. Numbers identify colors, not placement order.</p>',
           '<p>Build each section using its global row and column labels. Each square gets exactly one tile.',
           ' Number labels remain usable when printed in black and white. Print at 100% on A4 or Letter;',
           ' sheets are diagrams, not physical-size templates.</p>',
           '<p>RGB colors are approximations; verify actual pieces. Backing plates and frames are not included.</p>',
           f'<img class="overview" alt="Front-view mosaic overview" src="data:image/png;base64,{embedded}">',
           '<h2>Color key and total parts</h2><table class="palette"><thead><tr>',
           '<th>ID</th><th>Color</th><th>RGB</th><th>Needed</th><th>Available</th><th>Remaining</th>',
           '</tr></thead><tbody>']
    for color in colors:
        out.append(f'<tr><td>{color["id"]}</td><td><span class="swatch" style="background:{hex_rgb(color["rgb"])}"></span> '
                   f'{escape(color["name"])}</td><td>{escape(str(list(color["rgb"])))}</td>'
                   f'<td>{color["used"]}</td><td>{color["available"]}</td><td>{color["available"] - color["used"]}</td></tr>')
    out.append('</tbody></table><p>Generated with mosaic-parts-planner '
               f'{__version__}. Source SHA-256: <code>{plan["source"]["sha256"]}</code>.</p></header><main>')
    section = 0
    for top in range(0, height, size):
        for left in range(0, width, size):
            section += 1
            bottom, right = min(top + size, height), min(left + size, width)
            counts = Counter(grid[y][x] for y in range(top, bottom) for x in range(left, right))
            out.append(f'<section class="sheet" id="section-{section}"><h2>Section {section}</h2>'
                       f'<p>Rows {top + 1}–{bottom}, columns {left + 1}–{right} · '
                       f'{(bottom - top) * (right - left)} tiles · front view, top ↑</p>'
                       '<table class="grid"><caption>Global coordinates; cell numbers are color IDs</caption>'
                       '<thead><tr><th scope="col">Row / Col</th>')
            out.extend(f'<th scope="col">{x + 1}</th>' for x in range(left, right))
            out.append('</tr></thead><tbody>')
            for y in range(top, bottom):
                out.append(f'<tr><th scope="row">{y + 1}</th>')
                for x in range(left, right):
                    number = grid[y][x]
                    rgb = colors[number - 1]["rgb"]
                    out.append(f'<td style="background:{hex_rgb(rgb)}"><span>{number}</span></td>')
                out.append('</tr>')
            out.append('</tbody></table><table class="totals"><caption>Section parts</caption>'
                       '<thead><tr>' + '<th>Color ID</th><th>Count</th>' * 4 + '</tr></thead><tbody>')
            numbers = sorted(counts)
            for start in range(0, len(numbers), 4):
                out.append('<tr>')
                for offset in range(4):
                    if start + offset < len(numbers):
                        number = numbers[start + offset]
                        out.append(f'<td>{number}</td><td>{counts[number]}</td>')
                    else:
                        out.append('<td></td><td></td>')
                out.append('</tr>')
            out.append('</tbody></table></section>')
    out.append('</main></body></html>')
    return "\n".join(out) + "\n"


def convert(image_path: Path, inventory_path: Path, output: Path, width: int, height: int,
            fit="contain", background=(255, 255, 255), section_size=8):
    validate_grid(width, height)
    if type(section_size) is not int or not 1 <= section_size <= 16:
        raise InputError("section size must be an integer in 1–16")
    if output.exists() or output.is_symlink():
        raise InputError(f"output already exists: {output}; choose a new directory")
    colors = read_inventory(inventory_path)
    available = sum(c.available for c in colors)
    if available < width * height:
        raise InputError(f"insufficient inventory: need {width * height} tiles, have {available}; add tiles or reduce the grid")
    target, source = prepare_image(image_path, width, height, fit, background)
    pixels = list(target.get_flattened_data())
    assigned = assign(pixels, colors)
    used = Counter(assigned)
    plan = {"schema_version": 1, "generator": {"name": "mosaic-parts-planner", "version": __version__,
             "pillow": pillow_version}, "width": width, "height": height,
            "coordinates": "front view; row 1 column 1 is top-left; rows down, columns right",
            "tile": "flat single-layer 1x1", "source": source,
            "settings": {"fit": fit, "background": list(background), "section_size": section_size,
                         "resampling": "Lanczos", "color_space": "8-bit encoded RGB; ICC ignored"},
            "colors": [{"id": j + 1, **asdict(color), "used": used[j]} for j, color in enumerate(colors)],
            "grid": [[assigned[y * width + x] + 1 for x in range(width)] for y in range(height)]}
    comparison = compare(pixels, colors, assigned)
    mosaic = Image.new("RGB", (width, height))
    mosaic.putdata([colors[j].rgb for j in assigned])
    preview = mosaic.resize((width * 16, height * 16), Image.Resampling.NEAREST)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        target.save(staging / "target.png")
        preview.save(staging / "preview.png")
        write_json(staging / "placements.json", plan)
        write_json(staging / "comparison.json", comparison)
        with (staging / "parts.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["color_id", "name", "r", "g", "b", "available", "used", "remaining"])
            for j, color in enumerate(colors):
                writer.writerow([j + 1, spreadsheet_name(color.name), *color.rgb, color.available,
                                 used[j], color.available - used[j]])
        (staging / "instructions.html").write_text(instructions(plan, preview), encoding="utf-8")
        if output.exists() or output.is_symlink():
            raise InputError(f"output appeared during conversion: {output}; choose a new directory")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return comparison
