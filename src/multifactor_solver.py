#!/usr/bin/env python3
"""Greedy multi-factor solver for Santa 2026.

Unlike the single-factor pass, this solver can use every starting value as a
free factor and can open several reusable GCD factors.  It keeps only factors
whose construction cost is repaid by cheaper quotient representations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from anchor_difference_solver import digit_weight
from multiplicative_solver import build_factor_program, candidate_factors
from tiny_solver import (
    Puzzle,
    load_puzzles,
    read_submission,
    validate_program,
    write_submission,
)


def make_plan(
    puzzle: Puzzle, missing: list[int], factors: set[int]
) -> tuple[dict[int, tuple[int, int] | None], int, set[int]]:
    plan: dict[int, tuple[int, int] | None] = {}
    components = set()
    derived_count = 0

    for target in missing:
        best = (digit_weight(target, puzzle.value_limit), target, None)
        for factor in factors:
            if factor <= 1 or target % factor:
                continue
            quotient = target // factor
            if quotient <= 1:
                continue
            option = (digit_weight(quotient, puzzle.value_limit) + 1, quotient, factor)
            if option < best:
                best = option

        _, quotient_or_target, factor = best
        if factor is None:
            plan[target] = None
            components.add(target)
        else:
            quotient = quotient_or_target
            plan[target] = (factor, quotient)
            components.add(factor)
            components.add(quotient)
            derived_count += 1

    initial = set(puzzle.starting_values)
    estimate = sum(
        digit_weight(value, puzzle.value_limit)
        for value in components
        if value not in initial
    ) + derived_count
    return plan, estimate, components


def fits_register_budget(puzzle: Puzzle, components: set[int]) -> bool:
    initial = set(puzzle.starting_values)
    noninitial = len(components - initial)
    # Reserve three slots for 1, 2 and the moving power register.  This is a
    # conservative test; the builder may need fewer when values overlap.
    return noninitial + 3 <= puzzle.registers - len(puzzle.starting_values)


def solve_multifactor(puzzle: Puzzle):
    missing = sorted(set(puzzle.targets) - set(puzzle.starting_values))
    if not missing:
        return [], {"factors": [], "derived_targets": 0, "opened_factors": 0}

    free_factors = {value for value in puzzle.starting_values if value > 1}
    pool = candidate_factors(puzzle, missing) - free_factors
    chosen = set(free_factors)
    plan, estimate, components = make_plan(puzzle, missing, chosen)
    variants = [(set(chosen), plan, estimate, components)]

    # Greedy facility opening.  Each round adds the factor that most reduces
    # total component digit weight plus final multiplication costs.
    for _ in range(10):
        best = None
        for factor in pool - chosen:
            candidate_factors_set = chosen | {factor}
            candidate_plan, candidate_estimate, candidate_components = make_plan(
                puzzle, missing, candidate_factors_set
            )
            if candidate_estimate >= estimate:
                continue
            if not fits_register_budget(puzzle, candidate_components):
                continue
            option = (
                candidate_estimate,
                factor,
                candidate_plan,
                candidate_components,
            )
            if best is None or option[:2] < best[:2]:
                best = option
        if best is None:
            break
        estimate, factor, plan, components = best
        chosen.add(factor)
        variants.append((set(chosen), plan, estimate, components))

    best_program = None
    best_metadata = None
    for factors, candidate_plan, _, candidate_components in variants:
        if not fits_register_budget(puzzle, candidate_components):
            continue
        if not any(assignment is not None for assignment in candidate_plan.values()):
            continue
        try:
            program = build_factor_program(puzzle, candidate_plan)
        except RuntimeError:
            continue
        if best_program is None or len(program) < len(best_program):
            used_factors = sorted(
                {assignment[0] for assignment in candidate_plan.values() if assignment}
            )
            best_program = program
            best_metadata = {
                "factors": used_factors,
                "derived_targets": sum(
                    assignment is not None for assignment in candidate_plan.values()
                ),
                "opened_factors": sum(f not in free_factors for f in used_factors),
            }

    return best_program, best_metadata or {
        "factors": [],
        "derived_targets": 0,
        "opened_factors": 0,
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
    candidate_puzzles = 0
    improved_rows = []

    for puzzle in puzzles:
        candidate, metadata = solve_multifactor(puzzle)
        if candidate is None:
            continue
        validate_program(puzzle, candidate)
        candidate_puzzles += 1
        current_length = len(current_programs[puzzle.puzzle_id])
        if len(candidate) < current_length:
            selected_programs[puzzle.puzzle_id] = candidate
            improved_rows.append(
                {
                    "id": puzzle.puzzle_id,
                    "current_instructions": current_length,
                    "multifactor_instructions": len(candidate),
                    "improvement": current_length - len(candidate),
                    **metadata,
                }
            )

    for puzzle_id in order:
        validate_program(puzzle_by_id[puzzle_id], selected_programs[puzzle_id])
    write_submission(args.output, order, selected_programs)
    selected_total = sum(len(program) for program in selected_programs.values())

    report = {
        "solver": "greedy_multiple_reusable_factors",
        "current_submission": str(args.current),
        "output_submission": str(args.output),
        "current_score": current_total,
        "candidate_puzzles": candidate_puzzles,
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
