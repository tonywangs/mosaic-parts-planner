#!/usr/bin/env python3
"""One offline verification command, including every historical joint check."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    for command in [
        ['scripts/freeze_explorer.py', '--check'],
        ['scripts/verify_joint.py'],
        ['scripts/compare_explorer.py', '--check', 'experiments/explorer-results.json'],
        ['scripts/check_explorer_browser.py'],
    ]:
        print('+', sys.executable, *command, flush=True)
        subprocess.run([sys.executable, *command], cwd=ROOT, check=True, timeout=900)
    subprocess.run(['git', 'diff', '--check'], cwd=ROOT, check=True)
    print('Explorer verification passed, including historical checks, installed CLI, exhaustive enumeration and offline Chromium.')


if __name__ == '__main__':
    main()
