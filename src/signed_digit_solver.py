#!/usr/bin/env python3
"""Shared signed-digit solver for Santa 2026.

Targets use either ordinary binary digits or Non-Adjacent Form (NAF), whichever
has fewer non-zero digits and stays within value_limit.  A single power of two
is built upward, then streamed downward with exact divisions by two while all
target accumulators consume their signed digits.
"""

from __future__ import annotations

import argparse
import heapq
import json
from collections import Counter
from pathlib import Path

from power_basis_solver import is_power_of_two
from tiny_solver import (
    Instruction,
    Puzzle,
    load_puzzles,
    read_submission,
    validate_program,
    write_submission,
)


def binary_digits(value: int) -> dict[int, int]:
    return {bit: 1 for bit in range(value.bit_length()) if value >> bit & 1}


def naf_digits(value: int) -> dict[int, int]:
    """Return the canonical Non-Adjacent Form with digits in {-1, 0, 1}."""
    digits = {}
    bit = 0
    remaining = value
    while remaining:
        if remaining & 1:
            digit = 2 - (remaining & 3)
            digits[bit] = digit
            remaining -= digit
        remaining //= 2
        bit += 1
    return digits


def choose_digits(value: int, value_limit: int) -> dict[int, int]:
    ordinary = binary_digits(value)
    signed = naf_digits(value)
    signed_top_value = 1 << max(signed)
    if signed_top_value <= value_limit and len(signed) < len(ordinary):
        return signed
    return ordinary


def solve_signed_digits(puzzle: Puzzle) -> list[Instruction]:
    instructions: list[Instruction] = []
    initially_covered = set(puzzle.starting_values)
    missing = set(puzzle.targets) - initially_covered
    if not missing:
        return instructions

    free_registers = list(range(len(puzzle.starting_values), puzzle.registers))
    heapq.heapify(free_registers)

    one_register = next(
        (index for index, value in enumerate(puzzle.starting_values) if value == 1),
        None,
    )
    if one_register is None:
        one_register = heapq.heappop(free_registers)
        instructions.append(["/", 0, 0, one_register])
    missing.discard(1)
    if not missing:
        return instructions

    # Powers of two are covered automatically while the shared power is built.
    accumulator_targets = sorted(value for value in missing if not is_power_of_two(value))
    representations = {
        value: choose_digits(value, puzzle.value_limit)
        for value in accumulator_targets
    }
    missing_power_bits = [
        value.bit_length() - 1 for value in missing if is_power_of_two(value)
    ]
    representation_top_bits = [max(digits) for digits in representations.values()]
    highest_bit = max(missing_power_bits + representation_top_bits, default=0)

    if highest_bit == 0:
        return instructions

    two_register = next(
        (index for index, value in enumerate(puzzle.starting_values) if value == 2),
        None,
    )
    if two_register is None:
        two_register = heapq.heappop(free_registers)
        instructions.append(["+", one_register, one_register, two_register])

    current_power_register = two_register
    for bit in range(2, highest_bit + 1):
        if bit == 2:
            current_power_register = heapq.heappop(free_registers)
        instructions.append(
            ["+", current_power_register if bit > 2 else two_register,
             current_power_register if bit > 2 else two_register,
             current_power_register]
        )

    if not accumulator_targets:
        return instructions

    starts_at: dict[int, list[int]] = {}
    ends_at = {}
    for target, digits in representations.items():
        top_bit = max(digits)
        if digits[top_bit] != 1:
            raise AssertionError(f"{puzzle.puzzle_id}: non-positive leading digit")
        starts_at.setdefault(top_bit, []).append(target)
        ends_at[target] = min(digits)
    lowest_bit = min(ends_at.values())

    accumulators: dict[int, int] = {}
    for bit in range(highest_bit, lowest_bit - 1, -1):
        completing = []
        for target, accumulator in sorted(accumulators.items()):
            digit = representations[target].get(bit, 0)
            if digit == 1:
                instructions.append(
                    ["+", accumulator, current_power_register, accumulator]
                )
            elif digit == -1:
                instructions.append(
                    ["-", accumulator, current_power_register, accumulator]
                )
            if digit and bit == ends_at[target]:
                completing.append(target)
        for target in completing:
            heapq.heappush(free_registers, accumulators.pop(target))

        new_targets = list(starts_at.get(bit, ()))
        captured_power = False
        if new_targets and current_power_register != one_register:
            capture = min(new_targets, key=lambda value: (ends_at[value], value))
            accumulators[capture] = current_power_register
            new_targets.remove(capture)
            captured_power = True

        for target in new_targets:
            if not free_registers:
                raise RuntimeError(f"{puzzle.puzzle_id}: exhausted registers")
            destination = heapq.heappop(free_registers)
            instructions.append(
                ["*", current_power_register, one_register, destination]
            )
            accumulators[target] = destination

        if bit == lowest_bit:
            break

        if captured_power:
            if not free_registers:
                raise RuntimeError(f"{puzzle.puzzle_id}: no register for next power")
            next_power_register = heapq.heappop(free_registers)
        else:
            next_power_register = current_power_register
        instructions.append(
            ["/", current_power_register, two_register, next_power_register]
        )
        current_power_register = next_power_register

    if accumulators:
        raise AssertionError(
            f"{puzzle.puzzle_id}: unfinished targets {sorted(accumulators)}"
        )
    return instructions


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
    improved_rows = []
    representation_counts = Counter()

    for puzzle in puzzles:
        candidate = solve_signed_digits(puzzle)
        validate_program(puzzle, candidate)
        candidate_length = len(candidate)
        candidate_total += candidate_length
        for target in set(puzzle.targets) - set(puzzle.starting_values):
            if target == 1 or is_power_of_two(target):
                representation_counts["automatic_power"] += 1
            elif choose_digits(target, puzzle.value_limit) == naf_digits(target):
                representation_counts["naf"] += 1
            else:
                representation_counts["binary"] += 1
        current_length = len(current_programs[puzzle.puzzle_id])
        if candidate_length < current_length:
            selected_programs[puzzle.puzzle_id] = candidate
            improved_rows.append(
                {
                    "id": puzzle.puzzle_id,
                    "current_instructions": current_length,
                    "signed_digit_instructions": candidate_length,
                    "improvement": current_length - candidate_length,
                    "targets": len(puzzle.targets),
                    "value_limit": puzzle.value_limit,
                }
            )

    for puzzle_id in order:
        validate_program(puzzle_by_id[puzzle_id], selected_programs[puzzle_id])
    write_submission(args.output, order, selected_programs)

    selected_total = sum(len(program) for program in selected_programs.values())
    report = {
        "solver": "shared_signed_digit_stream",
        "current_submission": str(args.current),
        "output_submission": str(args.output),
        "current_score": current_total,
        "all_signed_digit_score": candidate_total,
        "selected_score": selected_total,
        "improved_puzzles": len(improved_rows),
        "total_improvement": current_total - selected_total,
        "representation_counts": dict(representation_counts),
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
                "improved_puzzles": len(improved_rows),
                "current_score": current_total,
                "all_signed_digit_score": candidate_total,
                "selected_score": selected_total,
                "improvement": current_total - selected_total,
                "representations": dict(representation_counts),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
