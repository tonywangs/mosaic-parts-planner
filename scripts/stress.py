#!/usr/bin/env python3
"""Exercise all grid/color limits with reproducible synthetic data."""

import json
from pathlib import Path
import random
import tempfile
from time import perf_counter

from PIL import Image

from mosaic_parts.export import convert, write_json
from check_bundle import check


def main():
    rng = random.Random(9771)
    with tempfile.TemporaryDirectory(prefix="mosaic-stress-") as temp:
        root = Path(temp)
        image = Image.new("RGB", (32, 32))
        image.putdata([tuple(rng.randrange(256) for _ in range(3)) for _ in range(1024)])
        image.save(root / "source.png")
        write_json(root / "inventory.json", {"colors": [
            {"name": f"Sample {i + 1}", "rgb": [rng.randrange(256) for _ in range(3)], "available": 32}
            for i in range(32)]})
        start = perf_counter()
        result = convert(root / "source.png", root / "inventory.json", root / "plan", 32, 32, section_size=16)
        elapsed = perf_counter() - start
        verified = check(root / "plan", root / "inventory.json")
        assert result["constrained"]["counts"] == [32] * 32
        print(json.dumps({"seed": 9771, "cells": 1024, "colors": 32,
                          "conversion_seconds": elapsed, "verification": verified,
                          "constrained": result["constrained"],
                          "nearest_unconstrained": result["nearest_unconstrained"]}, indent=2))


if __name__ == "__main__":
    main()
