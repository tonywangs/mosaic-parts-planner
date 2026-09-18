"""Input validation and bounded, explicit image preparation."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_CELLS = 1024
MAX_DIMENSION = 128
MAX_COLORS = 32
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_SIDE = 8192
MAX_INVENTORY_BYTES = 128 * 1024


class InputError(ValueError):
    """An actionable problem with user input."""


@dataclass(frozen=True)
class Color:
    name: str
    rgb: tuple[int, int, int]
    available: int


def bounded_read(path: Path, limit: int, label: str) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise InputError(f"{label} exceeds {limit:,} bytes; use a smaller file")
    return data


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def read_inventory(path: Path) -> list[Color]:
    try:
        raw = json.loads(bounded_read(path, MAX_INVENTORY_BYTES, "inventory"),
                         object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise InputError(f"inventory must be UTF-8 JSON: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"colors"}:
        raise InputError('inventory must be an object with exactly one key: "colors"')
    entries = raw["colors"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_COLORS:
        raise InputError(f"colors must be a list of 1–{MAX_COLORS} entries")
    colors, names = [], set()
    for i, entry in enumerate(entries, 1):
        prefix = f"color {i}"
        if not isinstance(entry, dict) or set(entry) != {"name", "rgb", "available"}:
            raise InputError(f"{prefix} must have exactly name, rgb, available")
        name, rgb, count = entry["name"], entry["rgb"], entry["available"]
        if (not isinstance(name, str) or not name.strip() or len(name) > 80
                or not name.isprintable() or name != name.strip()):
            raise InputError(f"{prefix} name must be 1–80 printable characters, without surrounding spaces")
        if name.casefold() in names:
            raise InputError(f"duplicate color name: {name!r}")
        if (not isinstance(rgb, list) or len(rgb) != 3
                or any(type(v) is not int or not 0 <= v <= 255 for v in rgb)):
            raise InputError(f"{prefix} rgb must be three integer channels in 0–255")
        if type(count) is not int or not 0 <= count <= 1_000_000_000:
            raise InputError(f"{prefix} available must be an integer in 0–1,000,000,000")
        names.add(name.casefold())
        colors.append(Color(name, tuple(rgb), count))
    return colors


def validate_grid(width: int, height: int):
    if any(type(v) is not int or not 1 <= v <= MAX_DIMENSION for v in (width, height)):
        raise InputError(f"width and height must each be integers in 1–{MAX_DIMENSION}")
    if width * height > MAX_CELLS:
        raise InputError(f"grid has {width * height:,} cells; maximum is {MAX_CELLS:,}; reduce width or height")


def prepare_image(path: Path, width: int, height: int, fit: str,
                  background: tuple[int, int, int]):
    validate_grid(width, height)
    if fit not in {"contain", "cover", "stretch"}:
        raise InputError("fit must be contain, cover, or stretch")
    if len(background) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in background):
        raise InputError("background must contain three integer channels in 0–255")
    data = bounded_read(path, MAX_IMAGE_BYTES, "image")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"PNG", "JPEG"}:
                    raise InputError("image must be PNG or JPEG; convert it first")
                if getattr(source, "n_frames", 1) != 1:
                    raise InputError("animated images are unsupported; export one frame as PNG")
                if source.width * source.height > MAX_IMAGE_PIXELS or max(source.size) > MAX_IMAGE_SIDE:
                    raise InputError("image exceeds 16,000,000 pixels or 8,192 pixels on a side; downsize it first")
                if source.mode not in {"1", "L", "LA", "P", "RGB", "RGBA"}:
                    raise InputError(f"image mode {source.mode} is unsupported; export 8-bit RGB/RGBA first")
                metadata = {"sha256": sha256(data).hexdigest(), "format": source.format,
                            "original_size": list(source.size), "original_mode": source.mode,
                            "icc_profile_ignored": bool(source.info.get("icc_profile"))}
                oriented = ImageOps.exif_transpose(source)
                metadata["oriented_size"] = list(oriented.size)
                rgba = oriented.convert("RGBA")
                matte = Image.new("RGBA", rgba.size, (*background, 255))
                image = Image.alpha_composite(matte, rgba).convert("RGB")
                size = (width, height)
                if fit == "cover":
                    result = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS,
                                          centering=(0.5, 0.5))
                elif fit == "contain":
                    scale = min(width / image.width, height / image.height)
                    fitted = (max(1, min(width, round(image.width * scale))),
                              max(1, min(height, round(image.height * scale))))
                    small = image.resize(fitted, Image.Resampling.LANCZOS)
                    result = Image.new("RGB", size, background)
                    result.paste(small, ((width - small.width) // 2, (height - small.height) // 2))
                else:
                    result = image.resize(size, Image.Resampling.LANCZOS)
                # Strip inherited EXIF/ICC metadata from all generated images.
                result.info.clear()
                return result, metadata
    except (UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning, OSError, SyntaxError, ValueError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError(f"cannot decode image; use a valid, bounded PNG/JPEG: {exc}") from exc
