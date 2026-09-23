# Fixed-color rectangular packing experiments

These are bounded synthetic CPU experiments, not a physical build or a perceptual
quality evaluation. All inputs are generated locally; no private data, paid
inference, or external dataset is needed. The optimizer is compared against an
inventory-aware row-major greedy packer and the all-1×1 baseline. Fixed grid colors
and rectangular-piece stock are identical for all three methods.

## Reproduce

From an installed checkout (Python 3.12.3 and Pillow 12.1.1 for saved results):

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/compare_packing.py --check experiments/packing-results.json
.venv/bin/python scripts/compare.py --check experiments/results.json
.venv/bin/python -m pip wheel --no-index --no-build-isolation \
  --find-links .wheelhouse --wheel-dir .wheelhouse .
.venv/bin/python scripts/verify_install.py --wheelhouse .wheelhouse
```

The wheel command assumes the documented wheelhouse was prepared already. It
needs local setuptools/wheel build tools and Pillow's platform wheel. The isolated
verification installs only the project wheel and Pillow into a fresh venv with no
system-site packages, runs both documented workflows with a socket audit guard,
reconstructs outputs independently, and compares repeat outputs byte-for-byte.
It runs the entire unit suite against the installed package, not the editable
checkout. Socket blocking is an additional test guard, not an OS network sandbox.

Optional browser verification (browser installation needs an initial download):

```sh
.venv/bin/python -m pip install -r requirements-print.txt
PLAYWRIGHT_BROWSERS_PATH=/tmp/mosaic-browser .venv/bin/python -m playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=/tmp/mosaic-browser .venv/bin/python scripts/check_packing_print.py \
  --check experiments/packing-print.json
PLAYWRIGHT_BROWSERS_PATH=/tmp/mosaic-browser .venv/bin/python scripts/check_print.py
```

`--check` recomputes results. It compares placements, counts, statuses, node counts
and hashes for completed/node-limited runs, but never compares elapsed time or
memory as exact constants. If either solve hits the wall deadline, that pair is
not expected to reproduce its explored prefix or incumbent. Every returned
incumbent is still independently validated. The tiny oracle cases must all reach
a proof and match their recorded results. Re-record intentional changes using
`--output experiments/packing-results.json` (benchmark) or
`--record experiments/packing-print.json` (browser).

## Independent tiny oracle

`packing-results.json` stores **300 seeded cases plus eight named adversarial
cases**. `scripts/packing_cases.py` uses Python `random.Random(230923)` to generate
1–4 columns by 1–3 rows, solid/random/checker patterns, zero/scarce/abundant stock,
and both rotation policies. Each full grid and inventory is saved, alongside
settings, true minimum, number of optimal tilings, number of all feasible tilings,
solver status/node count, and a placement hash. The named cases exercise:

- Rotation required versus forbidden for a horizontal domino.
- Two equal optimal domino covers of a 2×2 square.
- Disconnected same-color regions with a shared stock counter.
- Enough area per color but no color-preserving tiling.
- Scarce 2×2 stock, empty stock, and greedy failure requiring backtracking.

The oracle enumerates all tilings using coordinate sets. It does not import
candidate-generation, masks, bounds, or the production search. It uses no
objective pruning and is explicitly restricted to 12 cells. The optimizer gets
30 seconds and 1,000,000 nodes per tiny case. All **308 cases agreed** on feasibility
and minimum piece count. This provides substantial small-case evidence, not a
formal proof for every 256-cell instance. The original 1×1 assignment's 1,648
small optimality comparisons and four saved color-error comparisons remain intact.

## Bounded CPU comparisons

The 17 cases include the named fixtures, 256-cell solid/striped/checker grids, a
greedy-suboptimal case, two 100-cell seeded random grids, and explicit zero-node
and zero-time cutoffs. Normal limits are **2 seconds and 20,000 search nodes**.
Each algorithm/case runs once in a fresh subprocess, with a 15-second parent
watchdog. A watchdog violation fails the experiment rather than being counted as
a normal solver result. There is no statistical speed claim from one observation.

The greedy baseline chooses the largest currently fitting, stocked piece at the
first uncovered row-major cell; ties use color/shape order then rotation. It does
not backtrack. The unit baseline places only stocked 1×1 pieces. Their
`no_baseline_solution` means that baseline did not produce a cover, **not** that
the full packing problem is infeasible. The baseline code uses coordinate sets,
independently of the optimizer's mask generation; the optimizer separately uses
a greedy initializer of the same policy.

Measurements cover the whole algorithm call, including the optimizer's internal
validation, but exclude interpreter startup and the worker's subsequent validation.
Peak memory includes imports and validation. On Linux it is the process's
`/proc/self/status` VmHWM, converted from KiB to bytes; this avoids `ru_maxrss`'s
inherited pre-exec parent-memory floor. The fallback on other Unix platforms is
`getrusage`, labeled in each result. These are process high-water marks, not
incremental solver allocations. They do not establish a universal memory bound.
Every record includes platform, Python/Pillow/planner/solver versions, wall time,
CPU time, peak RSS, inputs, seed, settings, status, count and solution hash.

<!-- Observations below are generated from the saved, actually executed results. -->

Observed on 2026-09-23T08:31:07.602581+00:00 using Linux-6.8.0-124-generic-x86_64-with-glibc2.39:

| Case | Exact pieces / status | Greedy pieces | All-1×1 pieces | Exact CPU ms | Greedy CPU ms | Unit CPU ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| rotation_required | 1 / optimal | 1 | — | 0.277 | 0.055 | 0.026 |
| rotation_forbidden | — / infeasible | — | — | 0.170 | 0.034 | 0.028 |
| multiple_optima | 2 / optimal | 2 | — | 0.342 | 0.089 | 0.027 |
| disconnected_colors | 3 / optimal | 3 | — | 0.438 | 0.089 | 0.033 |
| enough_area_no_tiling | — / infeasible | — | — | 0.233 | 0.052 | 0.026 |
| scarce_square | 6 / optimal | 6 | — | 0.864 | 0.145 | 0.094 |
| greedy_trap | 5 / optimal | — | — | 0.478 | 0.124 | 0.077 |
| empty_stock | — / infeasible | — | — | 0.191 | 0.023 | 0.026 |
| solid_16x16 | 64 / optimal | 64 | 256 | 10.302 | 1.684 | 2.172 |
| stripes_16x16 | 128 / optimal | 128 | 256 | 7.779 | 2.905 | 2.610 |
| checker_16x16 | 256 / optimal | 256 | 256 | 7.358 | 5.436 | 2.387 |
| greedy_suboptimal | 5 / optimal | 6 | 8 | 0.680 | 0.164 | 0.150 |
| random_scarce | 53 / feasible | 53 | — | 101.757 | 1.553 | 1.017 |
| random_abundant | 53 / feasible | 53 | 100 | 95.960 | 0.994 | 1.301 |
| rotation_required_zero_nodes | 1 / feasible | 1 | — | 0.325 | 0.057 | 0.047 |
| greedy_trap_zero_nodes | — / unknown | — | — | 0.404 | 0.179 | 0.065 |
| zero_time | — / unknown | 1 | — | 0.158 | 0.072 | 0.021 |

Observed worker peak RSS ranged from 23,416,832 to 23,810,048 bytes; individual values and wall runtimes are in the JSON.

The small greedy-trap case is feasible with five pieces, although greedy fails.
Another case improves from six greedy pieces to five proven-optimal pieces.
The solid 256-cell case uses 64 squares and the striped case uses 128 dominoes,
both proven optimal. The checkerboard needs 256 units; there is no packing benefit.

The two 100-cell random cases reached the node bound with 53-piece incumbents,
matching greedy's count without proving optimality. The exact search spent more
CPU time without improving those incumbents. This is a negative result at these
settings, not evidence of general superiority. Increasing limits could help but
was not required to characterize this bounded run. Zero-node and zero-time cases
explicitly preserve both feasible incumbents and termination without a solution.

## Browser and install evidence

`packing-print.json` records Chromium 153.0.8010.12 checks for three cases on A4 and
Letter, with no external requests or browser errors. The image example's 24 cells
reconstruct as 10 pieces, three crossing boundaries; every diagram and placement
list stays on its own page. A separate four-section crossing fixture checks that
a 2×2 piece is listed only by its owner while appearing in all touched sections.
The dense 256-cell/32-color fixture exercises maximum section density, long
80-character names, and multi-page placement lists. Totals retain zero-stock
entries in CSV but omit them on paper. Color keys and totals can span pages with
repeated table headers. Physical printing and human assembly were not tested.

The isolated offline example completed with identical repeated JSON, PNG, CSV,
HTML, and solve-report bytes. Its optimum is ten pieces. The full suite covers
malformed JSON, grid/stock/resource limits, integer feasibility tampering,
forbidden rotations, duplicate input fields, invalid solver incumbents, solver
exceptions, staging cleanup, existing destinations, and interrupted search both
before and after finding a solution. Pinned dependencies and same-runtime tests
support artifact reproducibility for completed solves; time-limited outcomes
remain machine/load dependent.
