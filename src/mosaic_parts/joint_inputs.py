"""Strict, bounded inputs for joint color and rectangular piece optimization."""
from .model import InputError
from .packing_inputs import normalize_grid, normalize_inventory

MAX_CELLS = 64
MAX_COLORS = 8
MAX_ERROR = MAX_CELLS * 3 * 255 ** 2


def normalize_problem(raw):
    if not isinstance(raw, dict) or set(raw) != {'schema_version', 'width', 'height', 'colors', 'pixels', 'error_budget'}:
        raise InputError('joint problem requires schema_version, width, height, colors, pixels, error_budget')
    w, h = raw['width'], raw['height']
    if any(type(v) is not int or not 1 <= v <= 64 for v in (w, h)) or w * h > MAX_CELLS:
        raise InputError('joint optimization supports 1–64 cells, sides 1–64')
    if not isinstance(raw['colors'], list) or not 1 <= len(raw['colors']) <= MAX_COLORS:
        raise InputError('joint palette requires 1–8 colors')
    grid = normalize_grid({k: raw[k] for k in ('schema_version', 'width', 'height', 'colors')} |
                          {'grid': [[1] * w for _ in range(h)]})
    pixels = raw['pixels']
    if (not isinstance(pixels, list) or len(pixels) != w * h or
        any(not isinstance(p, list) or len(p) != 3 or
            any(type(v) is not int or not 0 <= v <= 255 for v in p) for p in pixels)):
        raise InputError('pixels must contain exactly width × height RGB integer triples, row-major')
    budget = raw['error_budget']
    if type(budget) is not int or not 0 <= budget <= MAX_ERROR:
        raise InputError(f'error budget must be an integer in 0–{MAX_ERROR}')
    return {k: grid[k] for k in ('schema_version', 'width', 'height', 'colors')} | {
        'pixels': [list(p) for p in pixels], 'error_budget': budget}


def inputs(problem, inventory):
    problem = normalize_problem(problem)
    inventory = normalize_inventory(inventory, problem)
    return problem, inventory
