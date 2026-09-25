# Explore image-error budgets offline

`explore` minimizes the number of pieces separately at each of 1–12 explicit
integer squared-RGB budgets. It samples the image once and uses identical pixels,
palette and stock for every search. No network service or optimizer package is
required. Use the [installation instructions](../README.md#install).

```sh
.venv/bin/mosaic-parts explore examples/source.png \
  --palette examples/joint-palette.json --inventory examples/pieces.json \
  --width 6 --height 4 --budgets 0 50000 100000 200000 400000 \
  --section-size 3 --output example-output/explorer
```

Open `example-output/explorer/comparison.html` directly in a browser. Its table
includes every requested budget, proof status, achieved error and piece count.
The labeled selection control supports keyboard navigation. Select a plan to
compare the sampled source and piece boundaries and download either a complete
ZIP bundle, printable HTML instructions, or a parts CSV. Everything is embedded;
the HTML remains functional when copied by itself to a disconnected machine.
JavaScript is required for downloads and selection; the complete table and all
previews remain readable without it. Extract the ZIP before opening instructions.

The same choice can be exported from saved JSON without running optimization:

```sh
.venv/bin/mosaic-parts export-plan example-output/explorer/comparison.json \
  --plan plan-3 --output example-output/explorer-selected
```

Both commands require a new output directory. The selected bundle uses the
existing joint-plan format: `placements.json`, `solve.json`, `preview.png`,
`parts.csv`, and `instructions.html`. Print at 100% on A4 or Letter; diagrams
are not physical-size templates. Refer to [assembly conventions](joint.md).

The sample has the following reproducible outcomes with default search limits:

| Budget | Status | Pieces | Achieved squared-RGB error | Plan |
| ---: | --- | ---: | ---: | --- |
| 0 | Proven infeasible | — | — | — |
| 50,000 | Proven optimal | 8 | 38,553 | plan-1 |
| 100,000 | Proven optimal | 7 | 61,053 | plan-2 |
| 200,000 | Proven optimal | 6 | 108,783 | plan-3 |
| 400,000 | Proven optimal | 6 | 108,783 | plan-3 |

These are mathematical statements about the sampled pixels, supported shapes
and supplied stock. RGB error does not establish perceptual fidelity or physical
color matching. Inventory authenticity, fit, backing plates, stability and actual
assembly remain unverified.

## Search bounds and outcomes

Existing limits apply: at most 64 cells, eight colors, and 1×1, 1×2 (optionally
rotatable), and 2×2 pieces. Each budget must be an integer from 0 to 12,484,800.
The [palette and inventory formats](joint.md) are unchanged.

| Flag | Default | Allowed |
| --- | ---: | --- |
| `--time-limit` | 10 seconds per distinct budget | finite 0–300 |
| `--node-limit` | 100,000 DFS nodes per distinct budget | integer 0–2,000,000 |
| `--total-time-limit` | 60 seconds across searches | finite 0–300 |
| `--total-node-limit` | 600,000 DFS nodes across searches | integer 0–2,000,000 |
| `--section-size` | 8 cells per printed section side | integer 1–8 |

Budgets run in input order; repeated values reuse their first outcome without
spending more search nodes. Each search receives the smaller of its per-budget
limit and the remaining whole-sweep allowance. Input sampling and final HTML/ZIP
serialization are outside the search deadline. Reconstruction between searches
counts against the remaining sweep time. Deadlines are cooperative, checked
during preprocessing, greedy initialization and DFS, so they can overshoot by
bounded work and scheduling delays. A node limit counts DFS calls, not candidate
generation or greedy initialization. Thus per-budget zero nodes can return a
validated greedy plan; a zero total node allowance starts no searches.

SIGINT (Ctrl-C) and SIGTERM request cooperative cancellation in the `explore`
CLI. The active solver retains any complete incumbent it has already found;
remaining distinct budgets become unresolved. Earlier outcomes and repeated
budgets are retained. Validation and atomic export finish so the report can be
inspected. Signals during sampling or serialization do not interrupt those
bounded operations. Further signals request the same cancellation, not a hard
kill. SIGKILL, power loss, or process crashes cannot promise cleanup or results.
The Python API accepts a `cancelled()` callback; it does not install handlers.

Status values in JSON map to the visible labels:

- `optimal`: proven minimum piece count at that budget, exhaustive search.
- `feasible`: independently validated plan, without an optimality proof.
- `infeasible`: exhaustive search proved no plan at that budget.
- `unknown`: unresolved, with no validated plan from that search.

Termination identifies exhaustion, per-search node/time limits, whole-sweep
limits, or cancellation. An active search clipped to the remaining whole-sweep
allowance still records `time_limit` or `node_limit`; subsequent unstarted searches
record `total_time_limit` or `total_node_limit`. `explore` exits 0 when it has
successfully exported a report, even if some or all budgets are unresolved or
infeasible; inspect its outcomes. Invalid inputs or failed exports exit 2.

Every returned plan is independently reconstructed to check coverage,
orientations, stock use, piece count and exact integer squared-RGB error. This
validator does not independently prove optimality; tiny-instance exhaustive
oracle tests verify the search's proof claims. Imported JSON has the same
validation, but it is not a cryptographic proof certificate. Only trust proof
provenance from a trusted run.

## What comparison means

The report labels nondominance **among returned plans only**: no other returned
plan has both no greater error and no greater piece count, with at least one
strict improvement. Equal objective values do not dominate one another.
The solver minimizes pieces only; it does not minimize error among tied
piece counts. Even proven piece minima at every requested budget do not prove
a Pareto frontier. Explicit sampled budgets do not exhaust all trade-offs.

`comparison.json` has `schema_version: 1`, `kind: mosaic-budget-explorer`, shared
`problem` and `inventory`, ordered `budgets` and `outcomes`, bounded `settings`,
`nodes_consumed`, and deduplicated `plans`. The shared problem's `error_budget`
is an input placeholder (0 for image CLI input); each outcome supplies its actual
budget. Each plan embeds a schema-3 joint plan at its first associated budget.
Geometry deduplication ignores placement IDs and list order but preserves color,
shape, position, orientation, width and height. All associated budget outcomes
retain their own proof status, even when they reference the same plan. A selected
export carries its first associated budget's status; it does not transfer proof
between budgets.

Exports use staging directories and rename only after reconstruction and writing
succeed. Existing outputs and symlinks are rejected. Handled failures remove
staging data. Export files are capped at 10 MiB and the bundle at 32 MiB; imported
comparison JSON is capped at 10 MiB and rejects duplicate object keys.

## Verification and recorded evidence

Prepare the optional verification dependencies on a connected machine:

```sh
.venv/bin/python -m pip install 'setuptools>=77' -r requirements-print.txt
.venv/bin/python -m pip wheel --wheel-dir .wheelhouse .
PLAYWRIGHT_BROWSERS_PATH=/tmp/mosaic-browser .venv/bin/python -m playwright install chromium
```

Then one command verifies the milestone entirely offline (including wheel build,
fresh isolated installation, sample CLI export, historical checks, 248 tiny
instances with five budget requests each, frozen benchmarks, keyboard selection,
network-blocked Chromium downloads, reconstruction and A4/Letter PDF smoke tests):

```sh
PLAYWRIGHT_BROWSERS_PATH=/tmp/mosaic-browser .venv/bin/python scripts/verify_explorer.py
```

A browser cache in another location can be selected using the same environment
variable. Verification does not download dependencies. See the
[experiment record](../experiments/explorer.md) for actual measurements and
repeatability limits. Old example images and historical benchmark files remain
unchanged.

## Related work

This is an engineering application of the established epsilon-constraint
method, not a new optimization algorithm. The [OpenMDAO practical course](https://openmdao.github.io/PracticalMDO/Notebooks/Optimization/multiobjective.html)
explains optimizing one objective while constraining another and includes an
existing implementation example. [Mesquita-Cunha, Figueira and Barbosa-Póvoa
(2021)](https://arxiv.org/abs/2109.02630) study epsilon-constraint methods for
representing multi-objective integer-programming trade-offs. This explorer does
not implement their adaptive representation algorithms or claim full-frontier
coverage. It reuses this project's bounded exact joint solver; see
[prior solver references](joint.md#related-work) for additional context.
