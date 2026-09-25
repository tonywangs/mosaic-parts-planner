#!/usr/bin/env python3
"""One-command milestone verification, including offline wheel and Chromium checks.

Prerequisites: project + requirements-print.txt installed, compatible Pillow
wheel in .wheelhouse, setuptools>=77, Chromium installed for Playwright.
PLAYWRIGHT_BROWSERS_PATH may select a local browser cache. No downloads here.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    commands = [
        ['scripts/freeze_joint.py', '--check'],
        ['-m', 'pip', 'wheel', '--no-index', '--no-build-isolation', '--find-links', '.wheelhouse', '--wheel-dir', '.wheelhouse', '.'],
        ['scripts/verify_install.py', '--wheelhouse', '.wheelhouse'],
        ['scripts/compare_packing.py', '--check', 'experiments/packing-results.json'],
        ['scripts/compare_joint.py', '--check', 'experiments/joint-results.json'],
        ['scripts/stress.py'],
        ['scripts/check_joint_print.py', '--check', 'experiments/joint-print.json'],
        ['scripts/check_packing_print.py'],
        ['scripts/check_print.py'],
    ]
    for command in commands:
        print('+', sys.executable, *command, flush=True)
        subprocess.run([sys.executable, *command], cwd=ROOT, check=True, timeout=300)
    subprocess.run(['git', 'diff', '--check'], cwd=ROOT, check=True)
    print('Joint milestone verification passed; all subprocess checks completed.')


if __name__ == '__main__':
    main()
