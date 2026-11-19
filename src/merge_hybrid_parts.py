#!/usr/bin/env python3
"""Merge independently optimized hybrid-planner ranges into one submission."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tiny_solver import (
    load_puzzles,
    read_submission,
    validate_program,
    write_submission,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--part", type=Path, action="append", required=True)
    parser.add_argument("--part-report", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    if len(args.part) != len(args.part_report):
        raise ValueError("--part and --part-report must have matching counts")

    puzzles = load_puzzles(args.puzzles)
    order, base_programs = read_submission(args.base)
    selected = dict(base_programs)
    covered_indices = set()
    reports = []

    for part_path, report_path in zip(args.part, args.part_report):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        start = report["start_index"]
        end = report["end_index"]
        _, part_programs = read_submission(part_path)
        for index in range(start, end):
            if index in covered_indices:
                raise ValueError(f"overlapping hybrid range at index {index}")
            puzzle_id = puzzles[index].puzzle_id
            selected[puzzle_id] = part_programs[puzzle_id]
            covered_indices.add(index)
        reports.append(report)

    expected = set(range(len(puzzles)))
    if covered_indices != expected:
        missing = sorted(expected - covered_indices)
        raise ValueError(f"hybrid ranges do not cover all puzzles: {missing[:20]}")

    for puzzle in puzzles:
        validate_program(puzzle, selected[puzzle.puzzle_id])
    write_submission(args.output, order, selected)

    base_score = sum(len(program) for program in base_programs.values())
    selected_score = sum(len(program) for program in selected.values())
    improved = [row for report in reports for row in report["improved"]]
    merged_report = {
        "solver": "hybrid_per_target_facility_local_beam_search",
        "base_submission": str(args.base),
        "output_submission": str(args.output),
        "base_score": base_score,
        "selected_score": selected_score,
        "total_improvement": base_score - selected_score,
        "improved_puzzles": len(improved),
        "part_reports": [str(path) for path in args.part_report],
        "largest_improvements": sorted(
            improved, key=lambda row: (-row["improvement"], row["id"])
        )[:50],
        "improved": sorted(improved, key=lambda row: row["id"]),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(merged_report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "valid": True,
                "parts": len(reports),
                "improved_puzzles": len(improved),
                "base_score": base_score,
                "selected_score": selected_score,
                "improvement": base_score - selected_score,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
