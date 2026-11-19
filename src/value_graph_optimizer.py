#!/usr/bin/env python3
"""Global value numbering, dead-code elimination and register allocation.

Arithmetic programs often create the same numeric value in several registers
so independent accumulators can be mutated in place.  This pass converts the
program to a value DAG, shares equal values, keeps only ancestors of targets,
then emits the DAG again with liveness-based register reuse.
"""

from __future__ import annotations

import argparse
import heapq
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from tiny_solver import (
    Instruction,
    Puzzle,
    load_puzzles,
    read_submission,
    validate_program,
    write_submission,
)


@dataclass(frozen=True)
class Recipe:
    operator: str
    left: int
    right: int
    order: int


def execute(operator: str, left: int, right: int) -> int:
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    return left // right


def extract_value_graph(
    puzzle: Puzzle, program: list[Instruction]
) -> tuple[dict[int, Recipe], int]:
    registers: list[int | None] = [None] * puzzle.registers
    known = set(puzzle.starting_values)
    recipes: dict[int, Recipe] = {}
    duplicate_results = 0
    for register, value in enumerate(puzzle.starting_values):
        registers[register] = value

    for order, (operator, left_register, right_register, destination) in enumerate(
        program
    ):
        left = registers[left_register]
        right = registers[right_register]
        assert left is not None and right is not None
        result = execute(operator, left, right)
        if result in known:
            duplicate_results += 1
        else:
            recipes[result] = Recipe(operator, left, right, order)
            known.add(result)
        registers[destination] = result
    return recipes, duplicate_results


def required_recipes(
    puzzle: Puzzle, recipes: dict[int, Recipe]
) -> tuple[set[int], set[int]]:
    initial = set(puzzle.starting_values)
    needed_values = set(puzzle.targets) - initial
    needed_recipes = set()
    stack = list(needed_values)
    while stack:
        value = stack.pop()
        if value in initial or value in needed_recipes:
            continue
        recipe = recipes.get(value)
        if recipe is None:
            raise RuntimeError(f"{puzzle.puzzle_id}: no recipe for required value {value}")
        needed_recipes.add(value)
        stack.append(recipe.left)
        stack.append(recipe.right)
    return needed_values, needed_recipes


def emit_value_graph(
    puzzle: Puzzle,
    recipes: dict[int, Recipe],
    needed_recipes: set[int],
) -> list[Instruction]:
    ordered_values = sorted(needed_recipes, key=lambda value: recipes[value].order)
    uses = Counter()
    for value in ordered_values:
        recipe = recipes[value]
        uses[recipe.left] += 1
        uses[recipe.right] += 1

    value_register: dict[int, int] = {}
    occupied = set()
    for register, value in enumerate(puzzle.starting_values):
        if uses[value] and value not in value_register:
            value_register[value] = register
            occupied.add(register)
    free = list(set(range(puzzle.registers)) - occupied)
    heapq.heapify(free)

    emitted: list[Instruction] = []
    for value in ordered_values:
        recipe = recipes[value]
        left_register = value_register[recipe.left]
        right_register = value_register[recipe.right]
        multiplicity = Counter((recipe.left, recipe.right))
        dying = [
            source
            for source, count in multiplicity.items()
            if uses[source] == count
        ]

        if dying:
            destination = value_register[dying[0]]
        elif free:
            destination = heapq.heappop(free)
        else:
            raise RuntimeError(f"{puzzle.puzzle_id}: value DAG exceeds 48 live registers")

        emitted.append(
            [recipe.operator, left_register, right_register, destination]
        )

        for source, count in multiplicity.items():
            uses[source] -= count
            if uses[source] == 0:
                old_register = value_register.pop(source)
                if old_register != destination:
                    heapq.heappush(free, old_register)

        if uses[value]:
            value_register[value] = destination
        else:
            heapq.heappush(free, destination)

    return emitted


def optimize_program(
    puzzle: Puzzle, program: list[Instruction]
) -> tuple[list[Instruction], dict]:
    recipes, duplicate_results = extract_value_graph(puzzle, program)
    _, needed_recipes = required_recipes(puzzle, recipes)
    optimized = emit_value_graph(puzzle, recipes, needed_recipes)
    return optimized, {
        "duplicate_results": duplicate_results,
        "dead_or_duplicate_instructions": len(program) - len(optimized),
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
    optimized_puzzles = 0
    register_pressure_failures = 0
    improved_rows = []

    for puzzle in puzzles:
        current = current_programs[puzzle.puzzle_id]
        try:
            candidate, metadata = optimize_program(puzzle, current)
            validate_program(puzzle, candidate)
        except RuntimeError:
            register_pressure_failures += 1
            continue
        optimized_puzzles += 1
        if len(candidate) < len(current):
            selected_programs[puzzle.puzzle_id] = candidate
            improved_rows.append(
                {
                    "id": puzzle.puzzle_id,
                    "current_instructions": len(current),
                    "optimized_instructions": len(candidate),
                    "improvement": len(current) - len(candidate),
                    **metadata,
                }
            )

    for puzzle_id in order:
        validate_program(puzzle_by_id[puzzle_id], selected_programs[puzzle_id])
    write_submission(args.output, order, selected_programs)
    selected_total = sum(len(program) for program in selected_programs.values())

    report = {
        "optimizer": "global_value_numbering_dce_liveness_allocation",
        "current_submission": str(args.current),
        "output_submission": str(args.output),
        "current_score": current_total,
        "selected_score": selected_total,
        "optimized_puzzles": optimized_puzzles,
        "register_pressure_failures": register_pressure_failures,
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
                "optimized_puzzles": optimized_puzzles,
                "register_pressure_failures": register_pressure_failures,
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
