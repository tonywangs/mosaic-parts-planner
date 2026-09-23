"""Deterministic, bounded branch-and-bound exact cover with inventory counters.

First empty cell branching is complete: in a disjoint rectangular cover its
piece must start at that cell, because all earlier cells are already covered.
No third-party optimizer, random branching, floating-point feasibility or cache.
"""

from dataclasses import dataclass
import time

from .packing_inputs import SHAPES, normalize_grid, normalize_inventory, validate_settings
from .packing_validate import validate_placements


class SolverError(RuntimeError):
    """Internal solver failure; no artifacts should be published."""


class _Stop(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    stock: int
    mask: int
    x: int
    y: int
    width: int
    height: int
    rotation: int


def _candidates(grid, inventory, check=lambda: None):
    w, h = grid["width"], grid["height"]
    by_anchor = [[] for _ in range(w * h)]
    for y in range(h):
        for x in range(w):
            check()
            for i, item in enumerate(inventory["pieces"]):
                if item["available"] == 0 or item["color_id"] != grid["grid"][y][x]:
                    continue
                pw, ph = SHAPES[item["shape"]]
                orientations = [(pw, ph, 0)] + ([(ph, pw, 90)] if item["rotate"] else [])
                for a, b, angle in orientations:
                    if x + a > w or y + b > h:
                        continue
                    if any(grid["grid"][yy][xx] != item["color_id"]
                           for yy in range(y, y + b) for xx in range(x, x + a)):
                        continue
                    mask = sum(1 << (yy * w + xx) for yy in range(y, y + b) for xx in range(x, x + a))
                    by_anchor[y * w + x].append(Candidate(i, mask, x, y, a, b, angle))
            by_anchor[y * w + x].sort(key=lambda c: (-c.width * c.height, c.stock, c.rotation))
    return by_anchor


def _placements(chosen, inventory):
    chosen = sorted(chosen, key=lambda c: (c.y, c.x, c.stock, c.rotation))
    return [{"id": i, "color_id": inventory["pieces"][c.stock]["color_id"],
             "shape": inventory["pieces"][c.stock]["shape"], "x": c.x, "y": c.y,
             "width": c.width, "height": c.height, "rotation": c.rotation}
            for i, c in enumerate(chosen, 1)]


def _greedy(candidates, inventory, total, check=lambda: None):
    left = [p["available"] for p in inventory["pieces"]]
    covered, chosen = 0, []
    full = (1 << total) - 1
    while covered != full:
        check()
        empty = full ^ covered
        first = (empty & -empty).bit_length() - 1
        choice = next((c for c in candidates[first] if left[c.stock] and not covered & c.mask), None)
        if choice is None:
            return None
        chosen.append(choice)
        left[choice.stock] -= 1
        covered |= choice.mask
    return chosen


def greedy(grid, inventory):
    grid = normalize_grid(grid)
    inventory = normalize_inventory(inventory, grid)
    chosen = _greedy(_candidates(grid, inventory), inventory, grid["width"] * grid["height"])
    if chosen is None:
        return None
    placements = _placements(chosen, inventory)
    validate_placements(grid, inventory, placements)
    return placements


def solve(grid, inventory, *, time_limit=10.0, node_limit=100_000, clock=time.monotonic):
    grid = normalize_grid(grid)
    inventory = normalize_inventory(inventory, grid)
    validate_settings(time_limit, node_limit)
    start = clock()
    nodes, best, reason = 0, None, "exhausted"
    width, height = grid["width"], grid["height"]
    total = width * height
    full = (1 << total) - 1
    stock = inventory["pieces"]
    left = [p["available"] for p in stock]
    colors = [c for row in grid["grid"] for c in row]
    remaining = [colors.count(i + 1) for i in range(len(grid["colors"]))]
    by_color = [[i for i, p in enumerate(stock) if p["color_id"] == c + 1]
                for c in range(len(remaining))]
    useful = [True] * len(stock)
    areas = [SHAPES[p["shape"]][0] * SHAPES[p["shape"]][1] for p in stock]
    by_color = [sorted(indices, key=lambda i: -areas[i]) for indices in by_color]

    def time_check():
        if clock() - start >= time_limit:
            raise _Stop("time_limit")

    def lower_bound():
        # Relax geometry and permit the last piece to overfill the area. This
        # can only underestimate required pieces, so pruning remains sound.
        bound = 0
        for color, count in enumerate(remaining):
            need = count
            for i in by_color[color]:
                if not useful[i]:
                    continue
                take = min(left[i], (need + areas[i] - 1) // areas[i])
                bound += take
                need = max(0, need - take * areas[i])
                if not need:
                    break
            if need:
                return total + 1
        return bound

    root_bound = lower_bound()
    chosen = []

    def search(covered):
        nonlocal nodes, best
        time_check()
        if nodes >= node_limit:
            raise _Stop("node_limit")
        nodes += 1
        if covered == full:
            if best is None or len(chosen) < len(best):
                best = list(chosen)
            return
        bound = lower_bound()
        if bound > total or (best is not None and len(chosen) + bound >= len(best)):
            return
        empty = full ^ covered
        first = (empty & -empty).bit_length() - 1
        for c in candidates[first]:
            if left[c.stock] and not covered & c.mask:
                color = stock[c.stock]["color_id"] - 1
                left[c.stock] -= 1
                remaining[color] -= areas[c.stock]
                chosen.append(c)
                search(covered | c.mask)
                chosen.pop()
                remaining[color] += areas[c.stock]
                left[c.stock] += 1

    try:
        time_check()
        # Preprocessing and greedy use the wall budget, but not the DFS node
        # budget. node_limit=0 can therefore return a valid greedy incumbent.
        candidates = _candidates(grid, inventory, time_check)
        usable = {c.stock for choices in candidates for c in choices}
        useful = [i in usable for i in range(len(stock))]
        root_bound = lower_bound()
        best = _greedy(candidates, inventory, total, time_check)
        search(0)
    except _Stop as exc:
        reason = str(exc)
    except Exception as exc:
        raise SolverError(f"packing solver failed: {type(exc).__name__}: {exc}") from exc
    status = ("optimal" if best is not None else "infeasible") if reason == "exhausted" else (
        "feasible" if best is not None else "unknown")
    placements = None if best is None else _placements(best, inventory)
    if placements is not None:
        # Separate integer-cell reconstruction before returning any incumbent.
        validate_placements(grid, inventory, placements)
    return {"status": status, "termination": reason, "nodes": nodes,
            "piece_count": None if placements is None else len(placements),
            "lower_bound": root_bound if root_bound <= total else None,
            "placements": placements}
