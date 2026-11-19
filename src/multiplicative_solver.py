#!/usr/bin/env python3
"""Common-factor solver for Santa 2026.

The solver searches for one reusable factor per puzzle.  Targets divisible by
that factor are produced as ``factor * quotient``; the factor, quotients and
remaining direct targets are built together by the signed-digit stream.
Candidate factors come from starting values and pairwise target GCDs.
"""

from __future__ import annotations

import argparse
import json
from math import gcd
from pathlib import Path

from anchor_difference_solver import build_retained_components, digit_weight
from tiny_solver import (
    Instruction,
    Puzzle,
    load_puzzles,
    read_submission,
    validate_program,
    write_submission,
)


def candidate_factors(puzzle: Puzzle, missing: list[int]) -> set[int]:
    """Return plausible factors without attempting expensive integer factoring."""
    candidates = {value for value in puzzle.starting_values if value > 1}
    for index, first in enumerate(missing):
        for second in missing[index + 1 :]:
            common = gcd(first, second)
            if common <= 1:
                continue
            candidates.add(common)

            # The odd part and power-of-two part can outperform the complete
            # GCD in signed-digit weight while retaining the same reuse.
            power_of_two = common & -common
            if power_of_two > 1:
                candidates.add(power_of_two)
            odd_part = common // power_of_two
            if odd_part > 1:
                candidates.add(odd_part)

    return candidates


def plan_for_factor(
    puzzle: Puzzle, missing: list[int], factor: int
) -> tuple[dict[int, tuple[int, int] | None], int] | None:
    """Create a factor plan and return it with a cheap cost estimate."""
    plan: dict[int, tuple[int, int] | None] = {}
    derived = 0
    for target in missing:
        if target % factor:
            plan[target] = None
            continue
        quotient = target // factor
        if quotient > 1 and digit_weight(quotient, puzzle.value_limit) + 1 < digit_weight(
            target, puzzle.value_limit
        ):
            plan[target] = (factor, quotient)
            derived += 1
        else:
            plan[target] = None

    if not derived:
        return None

    components = set()
    for target, assignment in plan.items():
        if assignment is None:
            components.add(target)
        else:
            components.update(assignment)

    initial = set(puzzle.starting_values)
    estimated_cost = sum(
        digit_weight(value, puzzle.value_limit)
        for value in components
        if value not in initial
    ) + derived
    return plan, estimated_cost


def build_factor_program(
    puzzle: Puzzle, plan: dict[int, tuple[int, int] | None]
) -> list[Instruction]:
    components = set()
    derived = []
    for target, assignment in plan.items():
        if assignment is None:
            components.add(target)
        else:
            factor, quotient = assignment
            components.add(factor)
            components.add(quotient)
            derived.append((target, factor, quotient))

    instructions, registers = build_retained_components(puzzle, components)
    scratch_candidates = sorted(set(range(puzzle.registers)) - set(registers.values()))
    if derived and not scratch_candidates:
        raise RuntimeError(f"{puzzle.puzzle_id}: no scratch register")
    scratch = scratch_candidates[0] if scratch_candidates else 0
    for _, factor, quotient in sorted(derived):
        instructions.append(["*", registers[factor], registers[quotient], scratch])
    return instructions


def solve_multiplicative(puzzle: Puzzle) -> tuple[list[Instruction] | None, dict]:
    missing = sorted(set(puzzle.targets) - set(puzzle.starting_values))
    if not missing:
        return [], {"factor": None, "derived_targets": 0, "candidates": 0}

    ranked = []
    for factor in candidate_factors(puzzle, missing):
        planned = plan_for_factor(puzzle, missing, factor)
        if planned is not None:
            plan, estimate = planned
            ranked.append((estimate, factor, plan))

    # Closely ranked estimates can yield different real stream costs.  Build
    # the best few and select using the exact instruction count.
    best_program = None
    best_factor = None
    best_derived = 0
    for _, factor, plan in sorted(ranked, key=lambda item: (item[0], item[1]))[:16]:
        try:
            program = build_factor_program(puzzle, plan)
        except RuntimeError:
            continue
        if best_program is None or len(program) < len(best_program):
            best_program = program
            best_factor = factor
            best_derived = sum(value is not None for value in plan.values())

    return best_program, {
        "factor": best_factor,
        "derived_targets": best_derived,
        "candidates": len(ranked),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    puzzles = load_puzzles(args.puzzles)
    order, current_programs = read_submission(args.current)
    puzzle_by_id = {puzzle.puzzle_id: puzzle for puzzle in puzzles}
    selected_programs = dict(current_programs)
    current_total = sum(len(program) for program in current_programs.values())
    candidate_total = 0
    candidate_puzzles = 0
    improved_rows = []

    for puzzle in puzzles:
        candidate, metadata = solve_multiplicative(puzzle)
        if candidate is None:
            continue
        validate_program(puzzle, candidate)
        candidate_puzzles += 1
        candidate_total += len(candidate)
        current_length = len(current_programs[puzzle.puzzle_id])
        if len(candidate) < current_length:
            selected_programs[puzzle.puzzle_id] = candidate
            improved_rows.append(
                {
                    "id": puzzle.puzzle_id,
                    "current_instructions": current_length,
                    "multiplicative_instructions": len(candidate),
                    "improvement": current_length - len(candidate),
                    **metadata,
                }
            )

    for puzzle_id in order:
        validate_program(puzzle_by_id[puzzle_id], selected_programs[puzzle_id])
    write_submission(args.output, order, selected_programs)
    selected_total = sum(len(program) for program in selected_programs.values())

    report = {
        "solver": "single_reusable_common_factor",
        "current_submission": str(args.current),
        "output_submission": str(args.output),
        "current_score": current_total,
        "candidate_puzzles": candidate_puzzles,
        "candidate_score_on_applicable_puzzles": candidate_total,
        "selected_score": selected_total,
        "improved_puzzles": len(improved_rows),
        "total_improvement": current_total - selected_total,
        "largest_improvements": sorted(
            improved_rows, key=lambda row: (-row["improvement"], row["id"])
        )[:50],
        "improved": sorted(improved_rows, key=lambda row: row["id"]),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "valid": True,
                "candidate_puzzles": candidate_puzzles,
                "improved_puzzles": len(improved_rows),
                "current_score": current_total,
                "selected_score": selected_total,
                "improvement": current_total - selected_total,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
