#!/usr/bin/env python3
"""Exact solver for the tiny family in Santa 2026 - The Elf Calculator.

For value_limit <= 16 every distinct positive value fits in a register.  An
optimal solution therefore never needs to discard a useful value or generate
an already available value.  Breadth-first search over subsets of available
values gives a proof of minimum instruction count.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path


Instruction = list[int | str]
Production = tuple[str, int, int, int]


@dataclass(frozen=True)
class Puzzle:
    puzzle_id: str
    starting_values: tuple[int, ...]
    targets: tuple[int, ...]
    value_limit: int
    registers: int


def load_puzzles(path: Path) -> list[Puzzle]:
    puzzles = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            puzzles.append(
                Puzzle(
                    puzzle_id=row["id"],
                    starting_values=tuple(json.loads(row["starting_values"])),
                    targets=tuple(json.loads(row["targets"])),
                    value_limit=int(row["value_limit"]),
                    registers=int(row["registers"]),
                )
            )
    return puzzles


def is_tiny(puzzle: Puzzle) -> bool:
    return (
        len(puzzle.targets) <= 4
        and max(puzzle.targets) <= 16
        and puzzle.value_limit <= 16
    )


def values_from_mask(mask: int, limit: int) -> list[int]:
    return [value for value in range(1, limit + 1) if mask & (1 << (value - 1))]


def candidate_productions(values: list[int], limit: int) -> dict[int, Production]:
    """Return one legal way to create every result reachable in one step."""
    candidates: dict[int, Production] = {}
    for offset, a in enumerate(values):
        for b in values[offset:]:
            result = a + b
            if result <= limit:
                candidates.setdefault(result, ("+", a, b, result))

            result = a * b
            if result <= limit:
                candidates.setdefault(result, ("*", a, b, result))

            if a != b:
                larger, smaller = max(a, b), min(a, b)
                result = larger - smaller
                candidates.setdefault(result, ("-", larger, smaller, result))
                if larger % smaller == 0:
                    result = larger // smaller
                    candidates.setdefault(result, ("/", larger, smaller, result))
            else:
                candidates.setdefault(1, ("/", a, a, 1))
    return candidates


def exact_value_program(puzzle: Puzzle) -> list[Production]:
    """Find a shortest sequence expressed with source and result values."""
    if puzzle.value_limit > 20:
        raise ValueError("subset BFS is intended only for tiny value limits")

    initial_mask = 0
    for value in puzzle.starting_values:
        initial_mask |= 1 << (value - 1)
    target_mask = 0
    for value in puzzle.targets:
        target_mask |= 1 << (value - 1)
    if initial_mask & target_mask == target_mask:
        return []

    queue = deque([initial_mask])
    parent: dict[int, tuple[int, Production] | None] = {initial_mask: None}
    goal_mask = None

    while queue:
        mask = queue.popleft()
        values = values_from_mask(mask, puzzle.value_limit)
        for result, production in candidate_productions(values, puzzle.value_limit).items():
            result_bit = 1 << (result - 1)
            if mask & result_bit:
                continue
            next_mask = mask | result_bit
            if next_mask in parent:
                continue
            parent[next_mask] = (mask, production)
            if next_mask & target_mask == target_mask:
                goal_mask = next_mask
                queue.clear()
                break
            queue.append(next_mask)

    if goal_mask is None:
        raise RuntimeError(f"no solution found for {puzzle.puzzle_id}")

    reversed_program = []
    cursor = goal_mask
    while cursor != initial_mask:
        previous, production = parent[cursor]  # type: ignore[misc]
        reversed_program.append(production)
        cursor = previous
    return list(reversed(reversed_program))


def allocate_registers(puzzle: Puzzle, value_program: list[Production]) -> list[Instruction]:
    """Assign one fresh register to each newly generated value."""
    value_to_register: dict[int, int] = {}
    for register, value in enumerate(puzzle.starting_values):
        value_to_register.setdefault(value, register)

    next_register = len(puzzle.starting_values)
    instructions: list[Instruction] = []
    for operator, left, right, result in value_program:
        if next_register >= puzzle.registers:
            raise RuntimeError("exact tiny solution unexpectedly exhausted registers")
        instructions.append(
            [operator, value_to_register[left], value_to_register[right], next_register]
        )
        value_to_register[result] = next_register
        next_register += 1
    return instructions


def solve(puzzle: Puzzle) -> list[Instruction]:
    return allocate_registers(puzzle, exact_value_program(puzzle))


def validate_program(puzzle: Puzzle, program: list[Instruction]) -> None:
    registers: list[int | None] = [None] * puzzle.registers
    for index, value in enumerate(puzzle.starting_values):
        registers[index] = value
    covered = set(puzzle.starting_values) & set(puzzle.targets)

    for step, instruction in enumerate(program, 1):
        if len(instruction) != 4:
            raise ValueError(f"{puzzle.puzzle_id}: malformed instruction {step}")
        operator, left_index, right_index, destination = instruction
        if operator not in {"+", "-", "*", "/"}:
            raise ValueError(f"{puzzle.puzzle_id}: bad operator at step {step}")
        if not all(
            isinstance(index, int) and 0 <= index < puzzle.registers
            for index in (left_index, right_index, destination)
        ):
            raise ValueError(f"{puzzle.puzzle_id}: bad register at step {step}")
        left = registers[left_index]
        right = registers[right_index]
        if left is None or right is None:
            raise ValueError(f"{puzzle.puzzle_id}: undefined source at step {step}")
        if operator == "+":
            result = left + right
        elif operator == "-":
            if left <= right:
                raise ValueError(f"{puzzle.puzzle_id}: illegal subtraction at step {step}")
            result = left - right
        elif operator == "*":
            result = left * right
        else:
            if left % right:
                raise ValueError(f"{puzzle.puzzle_id}: inexact division at step {step}")
            result = left // right
        if not 0 < result <= puzzle.value_limit:
            raise ValueError(f"{puzzle.puzzle_id}: out-of-range result at step {step}")
        registers[destination] = result
        if result in puzzle.targets:
            covered.add(result)

    missing = set(puzzle.targets) - covered
    if missing:
        raise ValueError(f"{puzzle.puzzle_id}: missing targets {sorted(missing)}")


def read_submission(path: Path) -> tuple[list[str], dict[str, list[Instruction]]]:
    order = []
    programs = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            order.append(row["id"])
            programs[row["id"]] = json.loads(row["program"])
    return order, programs


def write_submission(path: Path, order: list[str], programs: dict[str, list[Instruction]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "program"])
        writer.writeheader()
        for puzzle_id in order:
            writer.writerow(
                {
                    "id": puzzle_id,
                    "program": json.dumps(programs[puzzle_id], separators=(",", ":")),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--solutions", type=Path)
    args = parser.parse_args()

    puzzles = load_puzzles(args.puzzles)
    puzzle_by_id = {puzzle.puzzle_id: puzzle for puzzle in puzzles}
    order, programs = read_submission(args.baseline)
    old_total = sum(len(program) for program in programs.values())

    solved_rows = []
    for puzzle in puzzles:
        if not is_tiny(puzzle):
            continue
        old_length = len(programs[puzzle.puzzle_id])
        program = solve(puzzle)
        validate_program(puzzle, program)
        programs[puzzle.puzzle_id] = program
        lower_bound = len(set(puzzle.targets) - set(puzzle.starting_values))
        solved_rows.append(
            {
                "id": puzzle.puzzle_id,
                "starting_values": json.dumps(puzzle.starting_values),
                "targets": json.dumps(puzzle.targets),
                "value_limit": puzzle.value_limit,
                "lower_bound": lower_bound,
                "old_instructions": old_length,
                "optimal_instructions": len(program),
                "improvement": old_length - len(program),
                "program": json.dumps(program, separators=(",", ":")),
            }
        )

    for puzzle_id in order:
        validate_program(puzzle_by_id[puzzle_id], programs[puzzle_id])
    write_submission(args.output, order, programs)

    if args.solutions:
        args.solutions.parent.mkdir(parents=True, exist_ok=True)
        with args.solutions.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(solved_rows[0]))
            writer.writeheader()
            writer.writerows(solved_rows)

    new_total = sum(len(program) for program in programs.values())
    summary = {
        "tiny_puzzles": len(solved_rows),
        "optimal_at_lower_bound": sum(
            row["optimal_instructions"] == row["lower_bound"] for row in solved_rows
        ),
        "old_tiny_instructions": sum(row["old_instructions"] for row in solved_rows),
        "new_tiny_instructions": sum(row["optimal_instructions"] for row in solved_rows),
        "old_total": old_total,
        "new_total": new_total,
        "improvement": old_total - new_total,
        "output": str(args.output),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
