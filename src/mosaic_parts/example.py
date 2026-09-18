"""Small deterministic synthetic landscape; deliberately scarce dark tiles."""

from pathlib import Path
import shutil
import tempfile

from PIL import Image

from .export import write_json
from .model import InputError


def make_example(output: Path):
    if output.exists() or output.is_symlink():
        raise InputError(f"output already exists: {output}; choose a new directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        image = Image.new("RGB", (24, 16))
        for y in range(16):
            for x in range(24):
                if (x - 18) ** 2 + (y - 4) ** 2 <= 6:
                    rgb = (248, 208, 80)
                elif y >= 12 - abs(x - 10) // 3:
                    rgb = (35 + 2 * y, 70 + x, 70 + y)
                else:
                    rgb = (90 + y * 4, 160 + y * 2, 210 + y)
                image.putpixel((x, y), rgb)
        image.save(staging / "source.png")
        write_json(staging / "inventory.json", {"colors": [
            {"name": "Illustrative sky", "rgb": [110, 175, 220], "available": 220},
            {"name": "Illustrative dark teal", "rgb": [55, 85, 80], "available": 70},
            {"name": "Illustrative sand", "rgb": [225, 200, 145], "available": 100},
            {"name": "Illustrative gold", "rgb": [248, 208, 80], "available": 35},
        ]})
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
