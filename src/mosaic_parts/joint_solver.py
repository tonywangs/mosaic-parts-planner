"""Bounded integer branch-and-bound: minimize pieces under an RGB error budget.

Every rectangle of a complete cover containing the first empty cell starts
there. Branching over its stock/color/orientation therefore enumerates every
feasible tiling. Bounds relax geometry and color stock, never exclude a feasible
improvement. No numeric tolerances, optimizer dependency, randomness, or cache.
"""
from dataclasses import dataclass
import time

from .joint_inputs import inputs
from .joint_validate import validate
from .packing_inputs import SHAPES, validate_settings
from .packing_solver import SolverError, _Stop


@dataclass(frozen=True)
class Candidate:
    stock: int
    mask: int
    x: int
    y: int
    width: int
    height: int
    rotation: int
    error: int
    relaxed_error: int


def solve(problem, inventory, *, time_limit=10.0, node_limit=100_000, clock=time.monotonic, cancelled=lambda: False):
    problem, inventory = inputs(problem, inventory)
    validate_settings(time_limit, node_limit)
    start = clock()
    w, h = problem['width'], problem['height']
    total, budget = w * h, problem['error_budget']
    full = (1 << total) - 1
    stock = inventory['pieces']
    left = [p['available'] for p in stock]
    areas = [SHAPES[p['shape']][0] * SHAPES[p['shape']][1] for p in stock]
    order = sorted(range(len(stock)), key=lambda i: -areas[i])
    nodes, best, reason, generated = 0, None, 'exhausted', 0
    chosen = []

    def check():
        if cancelled():
            raise _Stop('cancelled')
        if clock() - start >= time_limit:
            raise _Stop('time_limit')

    def piece_bound(remaining):
        count = 0
        for i in order:
            take = min(left[i], (remaining + areas[i] - 1) // areas[i])
            count += take
            remaining = max(0, remaining - take * areas[i])
            if not remaining:
                return count
        return total + 1

    root_bound = piece_bound(total)

    def search(covered, error, relaxed):
        nonlocal nodes, best
        check()
        if nodes >= node_limit:
            raise _Stop('node_limit')
        nodes += 1
        if error + relaxed > budget:
            return
        if covered == full:
            if best is None or len(chosen) < len(best):
                best = list(chosen)
            return
        bound = piece_bound(total - covered.bit_count())
        if bound > total or (best is not None and len(chosen) + bound >= len(best)):
            return
        empty = full ^ covered
        first = (empty & -empty).bit_length() - 1
        for c in candidates[first]:
            if left[c.stock] and not covered & c.mask and error + c.error + relaxed - c.relaxed_error <= budget:
                left[c.stock] -= 1
                chosen.append(c)
                search(covered | c.mask, error + c.error, relaxed - c.relaxed_error)
                chosen.pop()
                left[c.stock] += 1

    def greedy(error_first):
        remaining = [p['available'] for p in stock]
        covered, error, relaxed, picked = 0, 0, sum(minimum), []
        while covered != full:
            check()
            empty = full ^ covered
            first = (empty & -empty).bit_length() - 1
            choices = candidates[first]
            if error_first:
                choices = sorted(choices, key=lambda c: (c.error - c.relaxed_error, -c.mask.bit_count(), c.stock, c.rotation))
            c = next((c for c in choices if remaining[c.stock] and not covered & c.mask
                      and error + c.error + relaxed - c.relaxed_error <= budget), None)
            if c is None:
                return None
            remaining[c.stock] -= 1
            picked.append(c)
            covered |= c.mask
            error += c.error
            relaxed -= c.relaxed_error
        return picked

    try:
        check()
        costs = [[sum((p[k] - color['rgb'][k]) ** 2 for k in range(3))
                  for color in problem['colors']] for p in problem['pixels']]
        available_colors = {p['color_id'] - 1 for p in stock if p['available']}
        minimum = [min((row[i] for i in available_colors), default=3 * 255**2 + 1) for row in costs]
        candidates = [[] for _ in range(total)]
        for y in range(h):
            for x in range(w):
                check()
                for i, item in enumerate(stock):
                    if not item['available']:
                        continue
                    a, b = SHAPES[item['shape']]
                    for cw, ch, angle in [(a, b, 0)] + ([(b, a, 90)] if item['rotate'] else []):
                        if x + cw > w or y + ch > h:
                            continue
                        cells = [yy*w+xx for yy in range(y, y+ch) for xx in range(x, x+cw)]
                        error = sum(costs[j][item['color_id']-1] for j in cells)
                        relaxed = sum(minimum[j] for j in cells)
                        generated += 1  # At most 64 × 8 × 4 = 2,048 candidates considered.
                        if error + sum(minimum) - relaxed <= budget:
                            candidates[y*w+x].append(Candidate(i, sum(1 << j for j in cells), x, y,
                                                              cw, ch, angle, error, relaxed))
                candidates[y*w+x].sort(key=lambda c: (-c.mask.bit_count(), c.error-c.relaxed_error, c.stock, c.rotation))
        for mode in (False, True):
            attempt = greedy(mode)
            if attempt is not None and (best is None or len(attempt) < len(best)):
                best = attempt
        search(0, 0, sum(minimum))
    except _Stop as exc:
        reason = str(exc)
    except Exception as exc:
        raise SolverError(f'joint solver failed: {type(exc).__name__}: {exc}') from exc
    status = ('optimal' if best is not None else 'infeasible') if reason == 'exhausted' else (
        'feasible' if best is not None else 'unknown')
    placements, error = None, None
    if best is not None:
        placements = [{'id': j, 'color_id': stock[c.stock]['color_id'], 'shape': stock[c.stock]['shape'],
                       'x': c.x, 'y': c.y, 'width': c.width, 'height': c.height, 'rotation': c.rotation}
                      for j, c in enumerate(best, 1)]
        error = validate(problem, inventory, placements)['image_error']
    return {'status': status, 'termination': reason, 'nodes': nodes, 'candidates_considered': generated,
            'piece_count': None if best is None else len(best), 'image_error': error,
            'lower_bound': root_bound if root_bound <= total else None, 'placements': placements}
