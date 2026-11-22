#!/usr/bin/env python3
"""Validate complete submissions and retain the shortest program per puzzle."""

import argparse
from collections import Counter
import json
from pathlib import Path

from tiny_solver import read_submission, write_submission
from validate_submission import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    validation_by_source = {str(path): validate(args.puzzles, path)
                            for path in [args.base, *args.candidate]}
    order, base = read_submission(args.base)
    selected = dict(base)
    winners = {puzzle_id: str(args.base) for puzzle_id in order}
    for path in args.candidate:
        _, candidate = read_submission(path)
        for puzzle_id in order:
            if len(candidate[puzzle_id]) < len(selected[puzzle_id]):
                selected[puzzle_id] = candidate[puzzle_id]
                winners[puzzle_id] = str(path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_submission(args.output, order, selected)
    validation = validate(args.puzzles, args.output)
    rows = [{"id": puzzle_id, "current_instructions": len(base[puzzle_id]),
             "selected_instructions": len(selected[puzzle_id]),
             "improvement": len(base[puzzle_id]) - len(selected[puzzle_id]),
             "source": winners[puzzle_id]} for puzzle_id in order]
    report = {"optimizer": "validated_best_per_puzzle", "base_submission": str(args.base),
              "candidates": list(map(str, args.candidate)), "output_submission": str(args.output),
              "current_score": sum(map(len, base.values())), "selected_score": validation["score"],
              "total_improvement": sum(r["improvement"] for r in rows),
              "improved_puzzles": sum(r["improvement"] > 0 for r in rows),
              "unchanged_puzzles": sum(r["improvement"] == 0 for r in rows),
              "regressions": sum(r["improvement"] < 0 for r in rows),
              "winning_sources": dict(Counter(winners.values())),
              "source_validations": validation_by_source, "validation": validation,
              "puzzles": rows}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items()
                     if k not in ("puzzles", "source_validations")}, indent=2))


if __name__ == "__main__":
    main()
