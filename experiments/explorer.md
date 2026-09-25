# Budget explorer experiments

Inputs were frozen in `explorer-suite.json` by `scripts/freeze_explorer.py` before
running `scripts/compare_explorer.py --record experiments/explorer-results.json`.
The generator uses seed **260926**, inherited from the preserved joint suite.
Sixteen cases include exact boundaries, ties, infeasible stock, rotation,
repeated/unordered budgets, larger noisy images, eight colors/64 cells, and
zero allowances. Full pixels, palettes, inventory, budget order and settings
are recorded; no private data or paid inference is used.

The recorded run has 74 budget requests: **34 proven optimal, 21 proven
infeasible, 12 validated feasible without proof, and 7 unresolved**. Repeated
requests are included in those counts. Every returned plan was independently
reconstructed. No unresolved case was dropped or counted as infeasible.
Single-process-per-case measured time summed to **1.7345 seconds**. Maximum
peak process RSS was **29,608 KiB**; the largest combined comparison JSON/HTML
output was **237,025 bytes**. Consult the machine-readable results for each
actual measurement, runtime/platform versions, output sizes and termination.

Measurements include search, validation and comparison export, exclude process
startup, and use `perf_counter` plus Linux `ru_maxrss` (including imports).
They are single measurements on this host, not performance comparisons or
statistically significant speed claims. Wall-clock deadlines and scheduling
can change returned incumbents. Node-limited results are normally deterministic
for these inputs and runtime versions. ZIP timestamps are fixed for repeatable
bytes. The verifier compares outcomes/output sizes only when neither run hit a
wall deadline; it does not require equal runtime or memory usage.

The independent exhaustive oracle in `scripts/joint_cases.py` enumerates
coordinate sets from the last uncovered cell, computes full leaf RGB errors,
and uses neither production candidate masks nor pruning bounds. Explorer tests
compare five budget requests on each of **248 instances** (240 seeded plus eight
named cases), including exact/below boundaries and repeated requests. Existing
joint and fixed-color regression/oracle tests remain part of verification.
There is no new solver claimed here: the baseline is the existing joint solver,
and the oracle checks the wrapper's per-budget outcomes.

`explorer-browser.json` records successful keyboard selection, downloaded ZIP/
HTML/CSV reconstruction, maximum-dimension/escaped-name cases, empty-result
states, and an actual sampled-image example in network-blocked Chromium.
A4 and Letter PDFs are generated and smoke-checked for instruction text;
this does not establish physical print accuracy or assembly suitability.
`results/tests.log` contains actual verification output.

Reproduce all checks using the command in [the explorer guide](../docs/explorer.md).
To rerun just this experiment:

```sh
.venv/bin/python scripts/freeze_explorer.py --check
.venv/bin/python scripts/compare_explorer.py --check experiments/explorer-results.json
```

Historical conversion, packing and joint measurements were preserved. Integer
squared-RGB error measures neither perceptual fidelity nor physical color match.
