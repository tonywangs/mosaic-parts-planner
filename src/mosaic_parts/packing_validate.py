"""Validate integer rectangles directly, without solver masks or candidates."""

from collections import Counter

from .model import InputError
from .packing_inputs import normalize_grid, normalize_inventory


def validate_placements(grid, inventory, placements):
    grid = normalize_grid(grid)
    inventory = normalize_inventory(inventory, grid)
    width, height = grid["width"], grid["height"]
    if not isinstance(placements, list) or not 1 <= len(placements) <= width * height:
        raise InputError("plan must contain 1 to grid-area placements")
    stock = {(p["color_id"], p["shape"]): p for p in inventory["pieces"]}
    covered = [[None] * width for _ in range(height)]
    used = Counter()
    fields = {"id", "color_id", "shape", "x", "y", "width", "height", "rotation"}
    for i, p in enumerate(placements, 1):
        if not isinstance(p, dict) or set(p) != fields:
            raise InputError("invalid placement fields")
        if any(type(p[k]) is not int for k in fields - {"shape"}):
            raise InputError("placement coordinates, IDs, dimensions, and rotation must be integers")
        if p["id"] != i or not isinstance(p["shape"], str):
            raise InputError("placement IDs must be consecutive from 1 and shape must be a string")
        key = (p["color_id"], p["shape"])
        if key not in stock:
            raise InputError("placement uses a color/shape absent from inventory")
        shape, rotation = p["shape"], p["rotation"]
        # Deliberately explicit: no shared orientation/candidate generation code.
        if shape == "1x1" and rotation == 0:
            expected = (1, 1)
        elif shape == "2x2" and rotation == 0:
            expected = (2, 2)
        elif shape == "1x2" and rotation == 0:
            expected = (1, 2)
        elif shape == "1x2" and rotation == 90 and stock[key]["rotate"]:
            expected = (2, 1)
        else:
            raise InputError("unsupported or forbidden placement orientation")
        if (p["width"], p["height"]) != expected:
            raise InputError("placement dimensions disagree with shape and rotation")
        if not (0 <= p["x"] <= width - p["width"] and 0 <= p["y"] <= height - p["height"]):
            raise InputError("placement is out of bounds")
        used[key] += 1
        if used[key] > stock[key]["available"]:
            raise InputError("placement exceeds piece inventory")
        for y in range(p["y"], p["y"] + p["height"]):
            for x in range(p["x"], p["x"] + p["width"]):
                if covered[y][x] is not None:
                    raise InputError("placements overlap")
                if grid["grid"][y][x] != p["color_id"]:
                    raise InputError("placement changes a grid color")
                covered[y][x] = p["color_id"]
    if any(c is None for row in covered for c in row):
        raise InputError("placements leave gaps")
    return used


def validate_plan(plan, grid, inventory):
    """Bind exported metadata to original inputs; optimality is not certified here."""
    if not isinstance(plan, dict) or type(plan.get("schema_version")) is not int or plan["schema_version"] != 2:
        raise InputError("rectangular plan must have schema_version 2")
    normalized = normalize_grid(grid)
    if plan.get("input_grid") != normalized or plan.get("inventory") != normalize_inventory(inventory, normalized):
        raise InputError("plan input copies do not match supplied inputs")
    used = validate_placements(normalized, inventory, plan.get("placements"))
    result = plan.get("result")
    if (not isinstance(result, dict) or result.get("status") not in ("optimal", "feasible")
            or type(result.get("piece_count")) is not int or result["piece_count"] != len(plan["placements"])):
        raise InputError("plan result disagrees with placements")
    return used
