"""Bounded JSON inputs for fixed-color rectangular packing."""

import json
import math
from pathlib import Path

from .model import InputError, _unique_object, bounded_read

MAX_PACK_CELLS = 256
MAX_PACK_SIDE = 64
MAX_JSON_BYTES = 256 * 1024
SHAPES = {"1x1": (1, 1), "1x2": (1, 2), "2x2": (2, 2)}


def read_json(path):
    try:
        return json.loads(bounded_read(Path(path), MAX_JSON_BYTES, "packing JSON"),
                          object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise InputError(f"packing input must be UTF-8 JSON: {exc}") from exc


def normalize_grid(raw):
    """Read core fields of a v1 conversion plan; unrelated metadata is ignored."""
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise InputError("grid must be a schema_version 1 placement grid")
    width, height = raw.get("width"), raw.get("height")
    if any(type(v) is not int or not 1 <= v <= MAX_PACK_SIDE for v in (width, height)):
        raise InputError(f"packing dimensions must be integers in 1–{MAX_PACK_SIDE}")
    if width * height > MAX_PACK_CELLS:
        raise InputError(f"packing supports at most {MAX_PACK_CELLS} cells")
    colors = raw.get("colors")
    if not isinstance(colors, list) or not 1 <= len(colors) <= 32:
        raise InputError("grid must have 1–32 colors")
    normalized, names = [], set()
    for i, color in enumerate(colors, 1):
        if not isinstance(color, dict) or type(color.get("id")) is not int or color["id"] != i:
            raise InputError("color IDs must be consecutive integers starting at 1")
        name, rgb = color.get("name"), color.get("rgb")
        if (not isinstance(name, str) or not 1 <= len(name) <= 80 or not name.isprintable()
                or name != name.strip() or not name or name.casefold() in names):
            raise InputError("color names must be unique, printable, 1–80 characters, without surrounding spaces")
        if not isinstance(rgb, list) or len(rgb) != 3 or any(type(c) is not int or not 0 <= c <= 255 for c in rgb):
            raise InputError("color RGB must contain three integer channels in 0–255")
        names.add(name.casefold())
        normalized.append({"id": i, "name": name, "rgb": list(rgb)})
    grid = raw.get("grid")
    if (not isinstance(grid, list) or len(grid) != height
            or any(not isinstance(row, list) or len(row) != width for row in grid)
            or any(type(c) is not int or not 1 <= c <= len(colors) for row in grid for c in row)):
        raise InputError("grid must match dimensions and contain only known integer color IDs")
    return {"schema_version": 1, "width": width, "height": height,
            "colors": normalized, "grid": [list(row) for row in grid]}


def normalize_inventory(raw, grid):
    if (not isinstance(raw, dict) or set(raw) != {"schema_version", "pieces"}
            or type(raw["schema_version"]) is not int or raw["schema_version"] != 1):
        raise InputError("piece inventory requires exactly schema_version: 1 and pieces")
    entries = raw["pieces"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 96:
        raise InputError("pieces must contain 1–96 entries; omitted color/shape pairs have zero stock")
    seen, pieces = set(), []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"color_id", "shape", "available", "rotate"}:
            raise InputError("each piece requires exactly color_id, shape, available, rotate")
        color, shape, available, rotate = (entry[k] for k in ("color_id", "shape", "available", "rotate"))
        if type(color) is not int or not 1 <= color <= len(grid["colors"]):
            raise InputError("piece color_id must be a known integer color ID")
        if not isinstance(shape, str) or shape not in SHAPES:
            raise InputError("piece shape must be 1x1, 1x2, or 2x2 (width × height)")
        if type(available) is not int or not 0 <= available <= 1_000_000_000:
            raise InputError("piece available must be an integer in 0–1,000,000,000")
        if type(rotate) is not bool or (shape != "1x2" and rotate):
            raise InputError("rotate must be boolean; only 1x2 may allow rotation")
        if (color, shape) in seen:
            raise InputError("duplicate color/shape inventory entry")
        seen.add((color, shape))
        pieces.append(dict(entry))
    return {"schema_version": 1, "pieces": sorted(pieces, key=lambda p: (p["color_id"], p["shape"]))}


def validate_settings(time_limit, node_limit, section_size=8):
    if (type(time_limit) not in (int, float) or not math.isfinite(time_limit)
            or not 0 <= time_limit <= 300):
        raise InputError("time limit must be finite seconds in 0–300")
    if type(node_limit) is not int or not 0 <= node_limit <= 2_000_000:
        raise InputError("node limit must be an integer in 0–2,000,000")
    if type(section_size) is not int or not 1 <= section_size <= 8:
        raise InputError("packing section size must be an integer in 1–8")
