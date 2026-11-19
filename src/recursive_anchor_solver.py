#!/usr/bin/env python3
"""Two-level anchor-and-difference solver for Santa 2026.

The first level represents targets as anchor +/- delta.  A second pass applies
the same idea to the anchors and deltas themselves before the signed-digit
builder is used.  Temporary delta registers are overwritten on their final
use so both levels still fit in the 48-register machine.
"""

from __future__ import annotations

import argparse
import heapq
import json
from collections import Counter
from pathlib import Path

from anchor_difference_solver import build_retained_components, choose_anchor_plan
from tiny_solver import (
    Instruction,
    Puzzle,
    load_puzzles,
    read_submission,
    validate_program,
    write_submission,
)


def plan_components(plan: dict[int, tuple[int, int] | None]) -> set[int]:
    components = set()
    for target, assignment in plan.items():
        if assignment is None:
            components.add(target)
        else:
            components.update(assignment)
    return components


def materialize_retained_values(
    puzzle: Puzzle,
    required: set[int],
    plan: dict[int, tuple[int, int] | None],
    instructions: list[Instruction],
    registers: dict[int, int],
) -> dict[int, int]:
    """Execute one anchor layer while retaining every required result."""
    relations = [
        (target, assignment[0], assignment[1])
        for target, assignment in sorted(plan.items())
        if assignment is not None and target not in registers
    ]
    uses = Counter(source for _, anchor, delta in relations for source in (anchor, delta))
    free = list(set(range(puzzle.registers)) - set(registers.values()))
    heapq.heapify(free)
    result_registers = {
        value: register for value, register in registers.items() if value in required
    }

    for target, anchor, delta in relations:
        anchor_register = registers[anchor]
        delta_register = registers[delta]

        destination = None
        for value, register in ((delta, delta_register), (anchor, anchor_register)):
            if value not in required and uses[value] == 1:
                destination = register
                break
        if destination is None:
            if not free:
                raise RuntimeError(f"{puzzle.puzzle_id}: no register for recursive anchor")
            destination = heapq.heappop(free)

        operator = "+" if target > anchor else "-"
        instructions.append([operator, anchor_register, delta_register, destination])

        for value in (anchor, delta):
            uses[value] -= 1
            if uses[value] == 0 and value not in required:
                old_register = registers.pop(value)
                if old_register != destination:
                    heapq.heappush(free, old_register)

        registers[target] = destination
        result_registers[target] = destination

    # Some required values may already have appeared as leaves even if their
    # plan also described a derivation.
    for value in required:
        if value in registers:
            result_registers[value] = registers[value]
    if set(result_registers) != required:
        missing = sorted(required - set(result_registers))
        raise AssertionError(f"{puzzle.puzzle_id}: missing retained values {missing}")
    return result_registers


def solve_recursive_anchor(puzzle: Puzzle) -> tuple[list[Instruction], dict]:
    outer_plan = choose_anchor_plan(puzzle)
    outer_components = plan_components(outer_plan)
    if not outer_components:
        return [], {"outer_derived": 0, "inner_derived": 0, "leaves": 0}

    component_puzzle = Puzzle(
        puzzle_id=puzzle.puzzle_id,
        starting_values=puzzle.starting_values,
        targets=tuple(sorted(outer_components)),
        value_limit=puzzle.value_limit,
        registers=puzzle.registers,
    )
    inner_plan = choose_anchor_plan(component_puzzle)
    leaves = plan_components(inner_plan)
    instructions, leaf_registers = build_retained_components(puzzle, leaves)
    for register, value in enumerate(puzzle.starting_values):
        if value in outer_components:
            leaf_registers.setdefault(value, register)
    component_registers = materialize_retained_values(
        puzzle,
        outer_components,
        inner_plan,
        instructions,
        dict(leaf_registers),
    )

    scratch_candidates = sorted(
        set(range(puzzle.registers)) - set(component_registers.values())
    )
    outer_relations = [
        (target, assignment[0], assignment[1])
        for target, assignment in sorted(outer_plan.items())
        if assignment is not None and target not in component_registers
    ]
    if outer_relations and not scratch_candidates:
        raise RuntimeError(f"{puzzle.puzzle_id}: no final scratch register")
    scratch = scratch_candidates[0] if scratch_candidates else 0
    for target, anchor, delta in outer_relations:
        operator = "+" if target > anchor else "-"
        instructions.append(
            [operator, component_registers[anchor], component_registers[delta], scratch]
        )

    return instructions, {
        "outer_derived": len(outer_relations),
        "inner_derived": sum(
            assignment is not None for assignment in inner_plan.values()
        ),
        "leaves": len(leaves),
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
    candidates = 0
    improved_rows = []

    for puzzle in puzzles:
        try:
            candidate, metadata = solve_recursive_anchor(puzzle)
            validate_program(puzzle, candidate)
        except RuntimeError:
            continue
        candidates += 1
        current_length = len(current_programs[puzzle.puzzle_id])
        if len(candidate) < current_length:
            selected_programs[puzzle.puzzle_id] = candidate
            improved_rows.append(
                {
                    "id": puzzle.puzzle_id,
                    "current_instructions": current_length,
                    "recursive_anchor_instructions": len(candidate),
                    "improvement": current_length - len(candidate),
                    **metadata,
                }
            )

    for puzzle_id in order:
        validate_program(puzzle_by_id[puzzle_id], selected_programs[puzzle_id])
    write_submission(args.output, order, selected_programs)
    selected_total = sum(len(program) for program in selected_programs.values())

    report = {
        "solver": "two_level_anchor_and_difference",
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
