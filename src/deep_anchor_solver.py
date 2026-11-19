#!/usr/bin/env python3
"""Three/four-level recursive anchor solver for Santa 2026."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from anchor_difference_solver import build_retained_components, choose_anchor_plan
from recursive_anchor_solver import materialize_retained_values, plan_components
from tiny_solver import (
    Instruction,
    Puzzle,
    load_puzzles,
    read_submission,
    validate_program,
    write_submission,
)


def anchor_layers(puzzle: Puzzle, depth: int):
    plans = []
    component_sets = []
    layer_puzzle = puzzle
    for _ in range(depth):
        plan = choose_anchor_plan(layer_puzzle)
        components = plan_components(plan)
        plans.append(plan)
        component_sets.append(components)
        if not components:
            break
        layer_puzzle = Puzzle(
            puzzle_id=puzzle.puzzle_id,
            starting_values=puzzle.starting_values,
            targets=tuple(sorted(components)),
            value_limit=puzzle.value_limit,
            registers=puzzle.registers,
        )
    return plans, component_sets


def solve_depth(puzzle: Puzzle, depth: int) -> tuple[list[Instruction], dict]:
    plans, component_sets = anchor_layers(puzzle, depth)
    if not component_sets or not component_sets[0]:
        return [], {"depth": depth, "leaves": 0, "derived_by_level": []}

    leaves = component_sets[-1]
    instructions, registers = build_retained_components(puzzle, leaves)

    # Initial registers are physically occupied throughout the reconstruction.
    # Keeping them in the map prevents a deeper layer from using one as scratch
    # before a shallower layer needs it as a free anchor.
    for register, value in enumerate(puzzle.starting_values):
        registers.setdefault(value, register)
    starts = set(puzzle.starting_values)

    for level in range(len(plans) - 1, 0, -1):
        required = component_sets[level - 1] | starts
        registers = materialize_retained_values(
            puzzle,
            required,
            plans[level],
            instructions,
            dict(registers),
        )

    outer_components = component_sets[0]
    component_registers = {
        value: register for value, register in registers.items() if value in outer_components
    }
    outer_relations = [
        (target, assignment[0], assignment[1])
        for target, assignment in sorted(plans[0].items())
        if assignment is not None and target not in component_registers
    ]
    scratch_candidates = sorted(
        set(range(puzzle.registers)) - set(component_registers.values())
    )
    if outer_relations and not scratch_candidates:
        raise RuntimeError(f"{puzzle.puzzle_id}: no final scratch register")
    scratch = scratch_candidates[0] if scratch_candidates else 0
    for target, anchor, delta in outer_relations:
        operator = "+" if target > anchor else "-"
        instructions.append(
            [operator, component_registers[anchor], component_registers[delta], scratch]
        )

    return instructions, {
        "depth": depth,
        "leaves": len(leaves),
        "derived_by_level": [
            sum(assignment is not None for assignment in plan.values()) for plan in plans
        ],
    }


def solve_deep_anchor(puzzle: Puzzle):
    best = None
    best_metadata = None
    for depth in (3, 4):
        try:
            candidate, metadata = solve_depth(puzzle, depth)
            validate_program(puzzle, candidate)
        except RuntimeError:
            continue
        if best is None or len(candidate) < len(best):
            best = candidate
            best_metadata = metadata
    return best, best_metadata


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
    candidates = 0
    improved_rows = []

    for puzzle in puzzles:
        candidate, metadata = solve_deep_anchor(puzzle)
        if candidate is None:
            continue
        candidates += 1
        current_length = len(current_programs[puzzle.puzzle_id])
        if len(candidate) < current_length:
            selected_programs[puzzle.puzzle_id] = candidate
            improved_rows.append(
                {
                    "id": puzzle.puzzle_id,
                    "current_instructions": current_length,
                    "deep_anchor_instructions": len(candidate),
                    "improvement": current_length - len(candidate),
                    **metadata,
                }
            )

    for puzzle_id in order:
        validate_program(puzzle_by_id[puzzle_id], selected_programs[puzzle_id])
    write_submission(args.output, order, selected_programs)
    selected_total = sum(len(program) for program in selected_programs.values())

    report = {
        "solver": "three_and_four_level_anchor",
        "current_submission": str(args.current),
        "output_submission": str(args.output),
        "current_score": current_total,
        "candidate_puzzles": candidates,
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
                "candidate_puzzles": candidates,
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
