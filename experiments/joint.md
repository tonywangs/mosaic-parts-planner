# Joint color and piece results

The benchmark inputs in `joint-suite.json` were frozen with `scripts/freeze_joint.py` before measurements. The generator uses seed 260926 and never invokes a solver. The suite SHA-256 is `1d5d46c81acf04e6bb54c3f8277d22949ea939e6c8e179d0396bab1d119e0ed2`. Reproduce the frozen inputs with `scripts/freeze_joint.py --check`. The 23 cases include exact error boundaries, rotation, scarce colors, tied optima, impossible geometry, structured/noisy larger grids, eight colors, and explicit zero-limit runs. All colors and images are synthetic.

Each row below compares the joint optimizer to the existing exact min-cost color assignment followed by fixed-color packing. Assignment receives color capacity equal to the total area of that color’s available pieces. Packing receives the identical piece inventory; both methods must meet the identical image-error budget. This area relaxation gives the sequential workflow a useful color assignment, but it cannot guarantee packability. Baseline “optimal” and “infeasible” refer to its chosen fixed-color grid, not to all possible recolorings. No tie exploration or joint feedback is added to the baseline.

Normal cases allow 20,000 DFS nodes and five solver seconds; two explicitly named limit cases override one bound to zero. The sequential time allowance includes color assignment, with the remainder passed to packing. The min-cost assignment is bounded by the 64-cell/eight-color input caps but has no internal cooperative deadline. A parent timeout guards each benchmark process. All joint feasible results are independently reconstructed and checked against the same sampled pixels, stock and budget.

## Recorded comparison

| Case | Budget | Joint status | Joint pieces / error | Sequential status | Sequential pieces / error |
| --- | ---: | --- | --- | --- | --- |
| boundary_below | 299 | optimal | 2 / 0 | optimal | 2 / 0 |
| boundary_exact | 300 | optimal | 1 / 300 | optimal | 2 / 0 |
| rotation_required | 300 | optimal | 1 / 300 | optimal | 1 / 300 |
| rotation_forbidden | 300 | infeasible | — / — | infeasible | — / 300 |
| scarce_nearest_color | 300 | optimal | 1 / 300 | optimal | 1 / 300 |
| tied_colors_and_tilings | 300 | optimal | 2 / 300 | optimal | 2 / 300 |
| geometry_impossible | 0 | infeasible | — / — | infeasible | — / 0 |
| empty_inventory | 300 | infeasible | — / — | infeasible | — / — |
| 4x3-blocks | 180000 | optimal | 4 / 0 | optimal | 4 / 0 |
| 4x3-checker | 180000 | optimal | 7 / 160275 | optimal | 12 / 0 |
| 4x3-noise | 180000 | optimal | 6 / 126675 | optimal | 8 / 0 |
| 4x4-blocks | 240000 | optimal | 4 / 0 | optimal | 4 / 0 |
| 4x4-checker | 240000 | feasible | 10 / 177075 | optimal | 16 / 0 |
| 4x4-noise | 240000 | optimal | 5 / 236550 | optimal | 8 / 0 |
| 6x4-blocks | 360000 | optimal | 6 / 0 | optimal | 6 / 0 |
| 6x4-checker | 360000 | feasible | 14 / 337350 | optimal | 24 / 0 |
| 6x4-noise | 360000 | optimal | 9 / 270150 | optimal | 13 / 0 |
| 8x8-blocks | 960000 | optimal | 16 / 0 | optimal | 16 / 0 |
| 8x8-checker | 960000 | feasible | 44 / 953925 | optimal | 64 / 0 |
| 8x8-noise | 960000 | feasible | 26 / 953925 | optimal | 39 / 0 |
| eight-colors-64-cells | 640000 | optimal | 16 / 86400 | optimal | 32 / 0 |
| no-nodes-with-incumbent | 300 | feasible | 1 / 300 | feasible | 2 / 0 |
| no-time-without-incumbent | 300 | unknown | — / — | unknown | — / — |

Joint results: 14 proven optima, five validated feasible incumbents, three proven infeasible cases, and one unknown result. Four nonzero-budget larger searches reached the 20,000-node limit without proving optimality; the fifth feasible result is the deliberate zero-node run. The zero-time case found no solution and is not labeled infeasible. These unsuccessful proofs are retained alongside successful ones.

For this suite, joint plans use fewer pieces on several inputs by spending allowed numerical error. This is not a perceptual improvement claim. Error is not a secondary optimization objective, so equal-piece solutions need not minimize error. There is no statistical speed or general superiority claim from these synthetic, single-run cases.

## Timing and memory

`joint-results.json` retains every case/method’s status, termination, piece count, error, feasibility, settings, elapsed wall seconds and peak process RSS, plus versions/platform/recording time. A fresh child process runs each measurement; wall time includes algorithm and validation but excludes startup. Linux `ru_maxrss` measures the worker high-water mark including imports, not incremental solver allocation. Timings and memory vary by machine. No GPU, paid inference, or private dataset was used.

- Joint: 0.000227–0.300524 seconds; peak RSS 23,296–23,552 KiB.
- Sequential: 0.000005–0.210214 seconds; peak RSS 23,296–23,296 KiB.

`scripts/compare_joint.py --check experiments/joint-results.json` reruns all measurements. It compares deterministic solution/search outcomes for runs that do not hit a time deadline, and independently validates any new incumbent. It does not require identical elapsed time or RSS. `--record PATH` creates a new measurement record; it does not modify the frozen inputs.

## Exhaustive and application checks

`tests/test_joint.py` compares feasibility and optimal piece count with independent exhaustive enumeration on 240 seeded cases (seed 260925) plus eight named edge cases. At most six cells and three colors keep enumeration modest. The oracle uses coordinate sets, branches on the last remaining cell, tries every rectangle containing that cell, and computes full-image error only at complete covers. It shares no production candidates, bitmasks, lower bounds, search pruning or error calculation. Input generation and the oracle are preserved in `scripts/joint_cases.py`. All 248 cases agree.

Additional checks exercise both greedy failures followed by a DFS-discovered incumbent, time/node termination with and without incumbents, malformed inputs and resource caps, all eight colors and 64 cells, injected solver/export failures, corrupted placements/metadata/CSV/visible HTML, preservation of existing output, and deterministic CLI bundles across hash seeds. Existing conversion and packing tests remain in the suite. The isolated installer runs the documented image-to-joint-plan example twice with Python socket operations blocked and checks the installed artifacts against a separately sampled source problem.

`joint-print.json` records Chromium 153.0.8010.12 checks for the sample, 64 cells/eight colors with recoloring, and a 1×64 grid. The browser context is offline and HTTP(S) requests are aborted. Source/plan images load, visible cells and parts lists are checked, and every section diagram and owned-placement list remains intact in A4 and Letter PDFs with background printing disabled. The sample has eight pages, the maximum-color case 21, and the narrow case 18, for both paper sizes; cover/key/parts information can span multiple pages. There were no external requests or browser errors. No physical printing or human assembly was tested.

Historical conversion/packing inputs, generated previews and measurement files remain unchanged. Full reproducible verification is described in [joint documentation](../docs/joint.md); plain command/test output is in `results/tests.log`.
