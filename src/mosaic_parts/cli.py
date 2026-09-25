"""Command line entry point. Runtime performs no network requests."""

import argparse
from pathlib import Path
import re
import sys

from . import __version__
from .example import make_example
from .export import convert
from .model import InputError
from .packing_export import pack
from .packing_solver import SolverError
from .joint_export import optimize
from .explorer_export import explore_image, read_report, export_selected, cancellation_signals


def background(value):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise argparse.ArgumentTypeError("background must be a quoted hex color, e.g. '#ffffff'")
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline image conversion and rectangular mosaic packing")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    example = commands.add_parser("example", help="create a deterministic synthetic PNG and illustrative inventory")
    example.add_argument("--output", type=Path, required=True, help="new directory for example inputs")
    build = commands.add_parser("convert", help="write a complete plan to a new directory")
    build.add_argument("image", type=Path)
    build.add_argument("--inventory", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--width", type=int, required=True, help="tile columns, 1–128")
    build.add_argument("--height", type=int, required=True, help="tile rows, 1–128; at most 1,024 cells total")
    build.add_argument("--fit", choices=("contain", "cover", "stretch"), default="contain")
    build.add_argument("--background", type=background, default=(255, 255, 255), help="alpha/letterbox matte, default '#ffffff'")
    build.add_argument("--section-size", type=int, default=8, help="maximum rows/columns per printed section, 1–16")
    packing = commands.add_parser("pack", help="pack a fixed-color placement grid with rectangular pieces")
    packing.add_argument("grid", type=Path, help="schema v1 placements.json from convert")
    packing.add_argument("--inventory", type=Path, required=True, help="separate rectangular piece inventory")
    packing.add_argument("--output", type=Path, required=True, help="new output directory")
    packing.add_argument("--time-limit", type=float, default=10.0, help="solver wall seconds, 0–300 (default 10)")
    packing.add_argument("--node-limit", type=int, default=100_000, help="DFS nodes, 0–2,000,000")
    packing.add_argument("--section-size", type=int, default=8, help="printed section side, 1–8")
    joint = commands.add_parser("optimize", help="jointly choose colors and pieces under an image-error budget")
    joint.add_argument("image", type=Path)
    joint.add_argument("--palette", type=Path, required=True, help="schema v1 colors with id, name, rgb")
    joint.add_argument("--inventory", type=Path, required=True)
    joint.add_argument("--output", type=Path, required=True)
    joint.add_argument("--width", type=int, required=True)
    joint.add_argument("--height", type=int, required=True, help="at most 64 cells total")
    joint.add_argument("--error-budget", type=int, required=True, help="maximum total integer squared-RGB error")
    joint.add_argument("--fit", choices=("contain", "cover", "stretch"), default="contain")
    joint.add_argument("--background", type=background, default=(255, 255, 255))
    joint.add_argument("--time-limit", type=float, default=10.0)
    joint.add_argument("--node-limit", type=int, default=100_000)
    joint.add_argument("--section-size", type=int, default=8)
    sweep = commands.add_parser("explore", help="compare up to 12 explicit image-error budgets offline")
    sweep.add_argument("image", type=Path)
    sweep.add_argument("--palette", type=Path, required=True)
    sweep.add_argument("--inventory", type=Path, required=True)
    sweep.add_argument("--output", type=Path, required=True)
    sweep.add_argument("--width", type=int, required=True)
    sweep.add_argument("--height", type=int, required=True)
    sweep.add_argument("--budgets", type=int, nargs='+', required=True)
    sweep.add_argument("--fit", choices=("contain", "cover", "stretch"), default="contain")
    sweep.add_argument("--background", type=background, default=(255, 255, 255))
    sweep.add_argument("--time-limit", type=float, default=10.0)
    sweep.add_argument("--node-limit", type=int, default=100_000)
    sweep.add_argument("--total-time-limit", type=float, default=60.0)
    sweep.add_argument("--total-node-limit", type=int, default=600_000)
    sweep.add_argument("--section-size", type=int, default=8)
    saved = commands.add_parser("export-plan", help="export a saved explorer plan without optimization")
    saved.add_argument("comparison", type=Path)
    saved.add_argument("--plan", required=True, help="plan ID from comparison, e.g. plan-1")
    saved.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "explore":
            with cancellation_signals() as cancelled:
                report = explore_image(args.image, args.palette, args.inventory, args.output, args.width, args.height,
                                       args.budgets, fit=args.fit, background=args.background,
                                       time_limit=args.time_limit, node_limit=args.node_limit,
                                       total_time_limit=args.total_time_limit, total_node_limit=args.total_node_limit,
                                       section_size=args.section_size, cancelled=cancelled)
            print(f"Compared {len(report['outcomes'])} budgets; {len(report['plans'])} validated plans in {args.output}")
            return 0
        elif args.command == "export-plan":
            export_selected(read_report(args.comparison), args.plan, args.output)
            print(f"Exported {args.plan} to {args.output} without optimization")
        elif args.command == "example":
            make_example(args.output)
            print(f"Created synthetic inputs in {args.output}")
        elif args.command == "optimize":
            result = optimize(args.image, args.palette, args.inventory, args.output, args.width, args.height,
                              args.error_budget, fit=args.fit, background=args.background,
                              time_limit=args.time_limit, node_limit=args.node_limit, section_size=args.section_size)
            print(f"Joint {result['status']}; termination {result['termination']}; pieces {result['piece_count']}; "
                  f"error {result['image_error']}/{args.error_budget}; results in {args.output}")
            return {"optimal": 0, "feasible": 0, "infeasible": 3, "unknown": 4}[result['status']]
        elif args.command == "pack":
            result = pack(args.grid, args.inventory, args.output, time_limit=args.time_limit,
                          node_limit=args.node_limit, section_size=args.section_size)
            print(f"Packing {result['status']}; termination {result['termination']}; "
                  f"pieces {result['piece_count']}; nodes {result['nodes']}; results in {args.output}")
            return {"optimal": 0, "feasible": 0, "infeasible": 3, "unknown": 4}[result["status"]]
        else:
            result = convert(args.image, args.inventory, args.output, args.width, args.height,
                             args.fit, args.background, args.section_size)
            print(f"Wrote {args.width * args.height} tiles to {args.output}; "
                  f"squared RGB error {result['constrained']['total_squared_rgb_error']}; "
                  f"unconstrained excess {result['nearest_unconstrained']['excess_tiles']} tiles")
        return 0
    except (InputError, OSError, SolverError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
