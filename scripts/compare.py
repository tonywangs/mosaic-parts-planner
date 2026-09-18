#!/usr/bin/env python3
"""Reproduce bounded synthetic comparisons; no downloaded data or inference."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import random
import tempfile

from PIL import Image, __version__ as pillow_version

from mosaic_parts import __version__
from mosaic_parts.example import make_example
from mosaic_parts.export import convert, write_json
from check_bundle import check


SEED = 9771


def run():
    results = []
    with tempfile.TemporaryDirectory(prefix="mosaic-comparison-") as temp:
        root = Path(temp)
        make_example(root / "landscape")
        cases = [("landscape_scarce_teal", root / "landscape" / "source.png",
                  root / "landscape" / "inventory.json", 24, 16)]
        rng = random.Random(SEED)
        for name, counts in (("noise_balanced", [64, 64, 64, 64]),
                             ("noise_scarce_red", [8, 84, 84, 84]),
                             ("noise_unlimited", [256, 256, 256, 256])):
            path = root / name
            path.mkdir()
            # Reset to the same seed: only capacity changes across noise cases.
            rng.seed(SEED)
            pixels = [tuple(rng.randrange(256) for _ in range(3)) for _ in range(256)]
            image = Image.new("RGB", (16, 16)); image.putdata(pixels)
            image.save(path / "source.png")
            palette = [(220, 45, 40), (40, 170, 90), (55, 80, 200), (230, 215, 170)]
            write_json(path / "inventory.json", {"colors": [
                {"name": f"Illustrative {j + 1}", "rgb": list(rgb), "available": count}
                for j, (rgb, count) in enumerate(zip(palette, counts))]})
            cases.append((name, path / "source.png", path / "inventory.json", 16, 16))
        for name, image, inventory, width, height in cases:
            output = root / (name + "-plan")
            comparison = convert(image, inventory, output, width, height)
            validation = check(output, inventory)
            results.append({"case": name, "width": width, "height": height,
                            "input_sha256": sha256(image.read_bytes()).hexdigest(),
                            "inventory": json.loads(inventory.read_text()),
                            "grid_sha256": sha256(json.dumps(json.loads((output / "placements.json").read_text())["grid"],
                                                             separators=(",", ":")).encode()).hexdigest(),
                            "constrained": comparison["constrained"],
                            "nearest_unconstrained": comparison["nearest_unconstrained"],
                            "independent_check": validation})
    return {"schema_version": 1, "seed": SEED, "generator": __version__, "pillow": pillow_version,
            "objective": "sum of squared distances in 8-bit encoded RGB",
            "fit": "contain", "background": [255, 255, 255], "cases": results,
            "interpretation": "Inventory feasibility can increase RGB error. This is not a perceptual or physical-color evaluation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--output", type=Path)
    action.add_argument("--check", type=Path, help="compare recomputed results against a saved result")
    args = parser.parse_args()
    result = run()
    if args.check:
        expected = json.loads(args.check.read_text(encoding="utf-8"))
        if result != expected:
            raise SystemExit("comparison differs from saved results")
        print(f"Reproduced {len(result['cases'])} saved comparison cases exactly")
    elif args.output:
        write_json(args.output, result)
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
