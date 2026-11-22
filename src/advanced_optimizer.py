#!/usr/bin/env python3
"""Benchmark and run executable-candidate search and bounded local synthesis."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import time

from recipe_graph_optimizer import optimize, rewrite_available_values
from short_synthesis_optimizer import optimize_short
from tiny_solver import load_puzzles, read_submission, validate_program, write_submission
from validate_submission import validate


def solve_job(job):
    puzzle, incumbent, donors, mode, cpu_budget, rounds, proposal_limit, windows = job
    started = time.process_time()
    deadline = started + cpu_budget
    candidate = incumbent
    metadata = {}
    if mode == "synthesis_first":
        candidate, _ = rewrite_available_values(puzzle, candidate, {})
        candidate, metadata = optimize_short(puzzle, candidate, max_windows=windows, deadline=deadline)
        metadata["synthesis_stage_saved"] = len(incumbent) - len(candidate)
        # The pilot showed synthesis has the best return on CPU. Use remaining
        # time for wider executable-candidate search without losing its result.
        if deadline - time.process_time() >= 0.1:
            candidate, graph_metadata = optimize(puzzle, candidate, donors, rounds,
                                                 proposal_limit, 8, deadline)
            metadata.update(graph_metadata)
    if mode in ("baseline", "wide", "combined"):
        graph_deadline = started + cpu_budget * 0.75 if mode == "combined" else deadline
        candidate, metadata = optimize(puzzle, incumbent, donors, rounds, proposal_limit,
                                       1 if mode == "baseline" else 8, graph_deadline)
    if mode in ("synthesis", "combined"):
        if mode == "synthesis":
            candidate, _ = rewrite_available_values(puzzle, candidate, {})
        candidate, synthesis = optimize_short(puzzle, candidate, max_windows=windows,
                                              deadline=deadline)
        metadata.update(synthesis)
        # Final cleanup is bounded by three passes; elapsed CPU includes it.
        cleaned, _ = rewrite_available_values(puzzle, candidate, {})
        if len(cleaned) < len(candidate):
            metadata["cleanup_saved"] = len(candidate) - len(cleaned)
            candidate = cleaned
    validate_program(puzzle, candidate)
    if len(candidate) >= len(incumbent):
        candidate = incumbent
    cpu_seconds = time.process_time() - started
    return mode, puzzle.puzzle_id, candidate, {
        "id": puzzle.puzzle_id, "current_instructions": len(incumbent),
        "selected_instructions": len(candidate), "improvement": len(incumbent) - len(candidate),
        "cpu_seconds": round(cpu_seconds, 6),
        "budget_overrun_seconds": round(max(0, cpu_seconds - cpu_budget), 6), **metadata}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", default=[])
    parser.add_argument("--modes", nargs="+", choices=("baseline", "wide", "synthesis", "combined", "synthesis_first"), default=["synthesis_first"])
    parser.add_argument("--prefix", required=True, help="Output stem under submissions/ and reports/")
    parser.add_argument("--cpu-budget", type=float, default=2.0)
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--proposal-limit", type=int, default=128)
    parser.add_argument("--windows", type=int, default=512)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int)
    args = parser.parse_args()
    puzzles = load_puzzles(args.puzzles)
    end = len(puzzles) if args.end_index is None else args.end_index
    if not 0 <= args.start_index <= end <= len(puzzles):
        parser.error("invalid puzzle range")
    if min(args.cpu_budget, args.workers, args.proposal_limit, args.windows) <= 0 or args.rounds < 0:
        parser.error("budgets must be positive and rounds nonnegative")
    if len(set(args.modes)) != len(args.modes) or Path(args.prefix).name != args.prefix:
        parser.error("modes must be unique and prefix a filename stem")
    for path in [args.current, *args.source]:
        validate(args.puzzles, path)
    order, current = read_submission(args.current)
    sources = [read_submission(path)[1] for path in args.source]
    rows = {mode: [] for mode in args.modes}
    selected = {mode: dict(current) for mode in args.modes}
    jobs = ((puzzle, current[puzzle.puzzle_id], [source[puzzle.puzzle_id] for source in sources],
             mode, args.cpu_budget, args.rounds, args.proposal_limit, args.windows)
            for puzzle in puzzles[args.start_index:end] for mode in args.modes)
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for mode, puzzle_id, program, metadata in executor.map(solve_job, jobs):
            selected[mode][puzzle_id] = program
            rows[mode].append(metadata)
            if mode == args.modes[-1] and len(rows[mode]) % 10 == 0:
                print(json.dumps({"processed_per_mode": len(rows[mode]),
                                  "saved": {m: sum(r["improvement"] for r in rows[m]) for m in args.modes},
                                  "wall_seconds": round(time.monotonic() - started, 2)}), flush=True)
    reports = {}
    for mode in args.modes:
        output = Path(f"submissions/submission_{args.prefix}_{mode}.csv")
        output.parent.mkdir(parents=True, exist_ok=True)
        write_submission(output, order, selected[mode])
        validation = validate(args.puzzles, output)
        report = {
            "optimizer": "executable_candidates_and_short_synthesis", "mode": mode,
            "current_submission": str(args.current), "sources": list(map(str, args.source)),
            "output_submission": str(output), "start_index": args.start_index, "end_index": end,
            "cpu_budget_per_puzzle": args.cpu_budget, "rounds": args.rounds,
            "proposal_limit": args.proposal_limit, "windows": args.windows,
            "candidate_width": 0 if mode == "synthesis" else (1 if mode == "baseline" else 8),
            "graph_budget_fraction": ("remaining_after_synthesis" if mode == "synthesis_first"
                                      else (0.75 if mode == "combined" else (0 if mode == "synthesis" else 1))),
            "workers": args.workers, "current_score": sum(map(len, current.values())),
            "selected_score": validation["score"],
            "total_improvement": sum(r["improvement"] for r in rows[mode]),
            "improved_puzzles": sum(r["improvement"] > 0 for r in rows[mode]),
            "cpu_seconds": round(sum(r["cpu_seconds"] for r in rows[mode]), 3),
            "max_budget_overrun_seconds": max((r["budget_overrun_seconds"] for r in rows[mode]), default=0),
            "validation": validation, "puzzles": rows[mode]}
        report_path = Path(f"reports/{args.prefix}_{mode}_report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        reports[mode] = {k: v for k, v in report.items() if k != "puzzles"}
    summary = {"modes": reports, "wall_seconds": round(time.monotonic() - started, 3)}
    Path(f"reports/{args.prefix}_comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
