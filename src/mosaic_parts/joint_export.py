"""Atomic joint-plan export with independently validated sampled inputs."""
import csv
from pathlib import Path
import platform
import shutil
import tempfile

from PIL import Image, ImageDraw, __version__ as pillow_version

from . import __version__
from .export import spreadsheet_name, write_json
from .joint_inputs import inputs, normalize_problem
from .joint_solver import solve
from .joint_validate import validate, validate_plan
from .model import InputError, prepare_image
from .packing_export import instructions, preview
from .packing_inputs import read_json, validate_settings


def load_problem(image, palette_path, width, height, error_budget, fit='contain', background=(255, 255, 255)):
    palette = read_json(palette_path)
    if (not isinstance(palette, dict) or set(palette) != {'schema_version', 'colors'}
            or type(palette['schema_version']) is not int or palette['schema_version'] != 1):
        raise InputError('palette requires exactly schema_version: 1 and colors')
    # Validate joint dimensions/palette before image allocation/decoding.
    count = width * height if type(width) is int and type(height) is int and 0 < width * height <= 64 else 0
    problem = normalize_problem({'schema_version': 1, 'width': width, 'height': height,
                                 'colors': palette['colors'], 'pixels': [[0, 0, 0]] * count,
                                 'error_budget': error_budget})
    sampled, metadata = prepare_image(Path(image), width, height, fit, background)
    problem['pixels'] = [list(p) for p in sampled.getdata()]
    return problem, metadata


def comparison(plan):
    problem = plan['problem']
    w, h, scale = problem['width'], problem['height'], 24
    source = Image.new('RGB', (w, h))
    source.putdata([tuple(p) for p in problem['pixels']])
    source = source.resize((w*scale, h*scale), Image.Resampling.NEAREST)
    packed = preview(plan)
    picture = Image.new('RGB', (w*scale*2 + 24, h*scale + 32), 'white')
    picture.paste(source, (0, 32))
    picture.paste(packed, (w*scale+24, 32))
    draw = ImageDraw.Draw(picture)
    draw.text((1, 4), 'Source', fill='black')
    draw.text((w*scale+24, 4), 'Plan', fill='black')
    for i in plan['recolored_cells']:
        x, y = w*scale+24+(i % w)*scale, 32+(i // w)*scale
        draw.rectangle((x+6, y+6, x+17, y+17), fill='white', outline='black')
        draw.text((x+8, y+6), '*', fill='black')
    return picture


def export(problem, inventory, output, *, time_limit=10.0, node_limit=100_000, section_size=8, source=None):
    problem, inventory = inputs(problem, inventory)
    validate_settings(time_limit, node_limit, section_size)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise InputError(f'output already exists: {output}; choose a new directory')
    answer = solve(problem, inventory, time_limit=time_limit, node_limit=node_limit)
    result = {k: v for k, v in answer.items() if k != 'placements'}
    settings = {'time_limit_seconds': time_limit, 'node_limit': node_limit, 'section_size': section_size}
    generator = {'name': 'mosaic-parts-planner', 'version': __version__, 'solver': 'joint-integer-dfs-v1',
                 'python': platform.python_version(), 'pillow': pillow_version}
    report = {'schema_version': 1, 'generator': generator, 'settings': settings, 'result': result,
              'problem': problem, 'inventory': inventory, 'source': source}
    plan = None
    if answer['placements'] is not None:
        checked = validate(problem, inventory, answer['placements'])
        plan = report | {'schema_version': 3, 'placements': answer['placements'],
                         'input_grid': checked['grid'], 'recolored_cells': checked['recolored_cells'],
                         'coordinates': 'front view; zero-based x right, y down; width × height'}
        checked = validate_plan(plan, problem, inventory)
    elif (result.get('status') not in ('infeasible', 'unknown') or result.get('piece_count') is not None
          or result.get('image_error') is not None or
          (result['status'] == 'infeasible') != (result.get('termination') == 'exhausted')):
        raise InputError('inconsistent solver result without placements')
    return save_report(report, plan, output)


def save_report(report, plan, output):
    """Write existing validated results without invoking optimization."""
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise InputError(f'output already exists: {output}; choose a new directory')
    problem, inventory = inputs(report['problem'], report['inventory'])
    result = report['result']
    if plan is not None:
        checked = validate_plan(plan, problem, inventory)
        validate_settings(plan['settings']['time_limit_seconds'], plan['settings']['node_limit'],
                          plan['settings']['section_size'])
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f'.{output.name}-', dir=output.parent))
    try:
        write_json(staging / 'solve.json', report)
        if plan is not None:
            write_json(staging / 'placements.json', plan)
            picture = comparison(plan)
            picture.save(staging / 'preview.png')
            w = problem['width']
            changed = ', '.join(f'R{i//w+1} C{i%w+1}' for i in plan['recolored_cells']) or 'none'
            note = (f'<section class="joint-summary"><h2>Joint color and piece optimization</h2>'
                    f'<p>Numerical squared-RGB error: <strong>{result["image_error"]}</strong>; '
                    f'requested budget: <strong>{problem["error_budget"]}</strong>. '
                    f'Status: {result["status"]}; termination: {result["termination"]}.</p>'
                    '<p>Source is the sampled image (left); plan is on the right. '
                    'Asterisks mark colors changed from the nearest palette color '
                    '(ties choose the lowest color ID). This is numerical color error, not perceptual fidelity.</p>'
                    f'<p class="recolored">Recolored cells (printed coordinates): {changed}.</p></section>')
            html = instructions(plan, picture).replace('<h2>Color key</h2>', note + '<h2>Color key</h2>')
            (staging / 'instructions.html').write_text(html, encoding='utf-8')
            with (staging / 'parts.csv').open('w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow(['color_id', 'name', 'shape', 'rotate', 'available', 'used', 'remaining'])
                for p in inventory['pieces']:
                    count = checked['used'][p['color_id'], p['shape']]
                    writer.writerow([p['color_id'], spreadsheet_name(problem['colors'][p['color_id']-1]['name']),
                                     p['shape'], str(p['rotate']).lower(), p['available'], count, p['available']-count])
        if any(p.stat().st_size > 10 * 1024**2 for p in staging.iterdir()):
            raise InputError('joint export exceeded per-file size limit')
        if output.exists() or output.is_symlink():
            raise InputError('output appeared during joint optimization; choose a new directory')
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return result


def optimize(image, palette, inventory, output, width, height, error_budget, *, fit='contain',
             background=(255, 255, 255), time_limit=10.0, node_limit=100_000, section_size=8):
    validate_settings(time_limit, node_limit, section_size)
    problem, metadata = load_problem(image, palette, width, height, error_budget, fit, background)
    metadata.update(fit=fit, background=list(background), sampling='EXIF transpose; alpha matte; Pillow LANCZOS; 8-bit RGB')
    return export(problem, read_json(inventory), output, time_limit=time_limit, node_limit=node_limit,
                  section_size=section_size, source=metadata)
