#!/usr/bin/env python3
"""Install wheels in a fresh venv offline, then run the documented example.

Run with a Python that has pip. The new venv deliberately has no pip and no
system packages; host pip's --python option installs into it without ensurepip.
The wheelhouse must contain this project wheel and its Pillow dependency.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv


ROOT = Path(__file__).resolve().parents[1]


def run(command, cwd, env):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    args = parser.parse_args()
    wheelhouse = args.wheelhouse.resolve()
    assert list(wheelhouse.glob("mosaic_parts_planner-*.whl")), "build the project wheel first"
    with tempfile.TemporaryDirectory(prefix="mosaic-isolated-install-") as temp:
        work = Path(temp)
        environment = work / "venv"
        venv.EnvBuilder(with_pip=False).create(environment)
        binary = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cli = environment / ("Scripts/mosaic-parts.exe" if os.name == "nt" else "bin/mosaic-parts")
        env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "PYTHONHOME")}
        env.update(PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONNOUSERSITE="1",
                   PIP_CONFIG_FILE=os.devnull)
        run([sys.executable, "-m", "pip", "--python", binary, "install", "--no-index",
             "--find-links", wheelhouse, "--only-binary=:all:", "mosaic-parts-planner==0.1.0"], work, env)
        run([binary, "-I", "-c", "import mosaic_parts, sys; from pathlib import Path; "
             "assert Path(mosaic_parts.__file__).is_relative_to(sys.prefix); print(mosaic_parts.__file__)"], work, env)
        # Disable socket creation for installed example/conversion processes.
        # This is an extra guard, not an OS-level network sandbox.
        guard = work / "guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text(
            'import sys\ndef block_network(event, args):\n'
            '    if event in ("socket.__new__", "socket.connect", "socket.getaddrinfo"):\n'
            '        raise RuntimeError("network disabled by offline verification")\n'
            'sys.addaudithook(block_network)\n', encoding="utf-8")
        env["PYTHONPATH"] = str(guard)
        run([cli, "example", "--output", work / "input"], work, env)
        for name in ("first", "second"):
            run([cli, "convert", work / "input/source.png", "--inventory", work / "input/inventory.json",
                 "--width", "24", "--height", "16", "--output", work / name], work, env)
            run([binary, ROOT / "scripts/check_bundle.py", work / name, work / "input/inventory.json"], work, env)
        hashes = {}
        for path in sorted((work / "first").iterdir()):
            assert path.read_bytes() == (work / "second" / path.name).read_bytes(), path.name
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        run([binary, "-m", "unittest", "discover", "-s", ROOT / "tests", "-v"], work, env)
        run([binary, ROOT / "scripts/compare.py", "--check", ROOT / "experiments/results.json"], work, env)
        print(json.dumps({"isolated_install": "passed", "offline_example": "passed",
                          "all_artifacts_identical": True, "sha256": hashes}, indent=2))


if __name__ == "__main__":
    main()
