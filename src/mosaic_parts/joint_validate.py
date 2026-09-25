"""Reconstruct joint plans without importing solver candidates, masks or costs."""
from .model import InputError
from .joint_inputs import inputs
from .packing_validate import validate_placements


def validate(problem, inventory, placements):
    problem, inventory = inputs(problem, inventory)
    w, h = problem['width'], problem['height']
    rows = [[0] * w for _ in range(h)]
    if not isinstance(placements, list) or not 1 <= len(placements) <= w * h:
        raise InputError('joint plan needs 1 to area placements')
    for p in placements:
        if (not isinstance(p, dict) or any(type(p.get(k)) is not int for k in
                ('x', 'y', 'width', 'height', 'color_id'))):
            raise InputError('invalid joint placement')
        x, y, a, b, c = (p[k] for k in ('x', 'y', 'width', 'height', 'color_id'))
        if not (1 <= a <= 2 and 1 <= b <= 2 and 0 <= x <= w-a and 0 <= y <= h-b
                and 1 <= c <= len(problem['colors'])):
            raise InputError('invalid joint placement bounds/color')
        for yy in range(y, y+b):
            for xx in range(x, x+a):
                if rows[yy][xx]:
                    raise InputError('joint placements overlap')
                rows[yy][xx] = c
    if any(c == 0 for row in rows for c in row):
        raise InputError('joint placements leave gaps')
    grid = {k: problem[k] for k in ('schema_version', 'width', 'height', 'colors')} | {'grid': rows}
    used = validate_placements(grid, inventory, placements)
    error, recolored, nearest = 0, [], []
    for i, source in enumerate(problem['pixels']):
        c = rows[i // w][i % w]
        rgb = problem['colors'][c-1]['rgb']
        error += sum((source[k] - rgb[k]) ** 2 for k in range(3))
        distances = [sum((source[k] - col['rgb'][k]) ** 2 for k in range(3)) for col in problem['colors']]
        closest = distances.index(min(distances)) + 1
        nearest.append(closest)
        if c != closest:
            recolored.append(i)
    if error > problem['error_budget']:
        raise InputError('joint plan exceeds image-error budget')
    return {'grid': grid, 'used': used, 'image_error': error, 'piece_count': len(placements),
            'recolored_cells': recolored, 'nearest_color_ids': nearest}


def validate_plan(plan, problem, inventory):
    problem, inventory = inputs(problem, inventory)
    if (not isinstance(plan, dict) or type(plan.get('schema_version')) is not int or plan['schema_version'] != 3
            or plan.get('problem') != problem or plan.get('inventory') != inventory):
        raise InputError('joint plan input copies or schema do not match')
    checked = validate(problem, inventory, plan.get('placements'))
    result = plan.get('result')
    if (not isinstance(result, dict) or result.get('status') not in ('optimal', 'feasible')
            or result.get('termination') not in ('exhausted', 'node_limit', 'time_limit')
            or (result['status'] == 'optimal') != (result['termination'] == 'exhausted')):
        raise InputError('inconsistent joint result status')
    for k in ('image_error', 'piece_count'):
        if type(result.get(k)) is not int or result[k] != checked[k]:
            raise InputError(f'joint result {k} disagrees with reconstruction')
    if plan.get('input_grid') != checked['grid'] or plan.get('recolored_cells') != checked['recolored_cells']:
        raise InputError('joint grid/recolor metadata disagrees with reconstruction')
    return checked
