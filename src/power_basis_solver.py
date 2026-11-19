#!/usr/bin/env python3
"""Shared streaming power-of-two solver for Santa 2026.

Instead of rebuilding the binary expansion of every target independently, the
solver generates each power of two once and adds it to every target that needs
that bit.  Target accumulators are released as soon as their value is covered.
"""

from __future__ import annotations

import argparse
import heapq
import json
from collections import Counter
from pathlib import Path

from tiny_solver import (
    Instruction,
    Puzzle,
    load_puzzles,
    read_submission,
    validate_program,
    write_submission,
)


def is_power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


def trailing_zero_count(value: int) -> int:
    return (value & -value).bit_length() - 1


def solve_power_basis(puzzle: Puzzle) -> list[Instruction]:
    """Build every target using a shared, low-to-high stream of powers of two."""
    instructions: list[Instruction] = []
    covered_initially = set(puzzle.starting_values)
    missing = set(puzzle.targets) - covered_initially
    if not missing:
        return instructions

    free_registers = list(range(len(puzzle.starting_values), puzzle.registers))
    heapq.heapify(free_registers)

    one_register = next(
        (index for index, value in enumerate(puzzle.starting_values) if value == 1),
        None,
    )
    if one_register is None:
        if not free_registers:
            raise RuntimeError(f"{puzzle.puzzle_id}: no register available for constant 1")
        one_register = heapq.heappop(free_registers)
        instructions.append(["/", 0, 0, one_register])

    # Creating or already having 1 covers target 1 without a separate accumulator.
    missing.discard(1)
    if not missing:
        return instructions

    highest_bit = max(value.bit_length() - 1 for value in missing)
    accumulator_targets = sorted(value for value in missing if not is_power_of_two(value))
    first_bit = {value: trailing_zero_count(value) for value in accumulator_targets}
    last_bit = {value: value.bit_length() - 1 for value in accumulator_targets}
    starts_at: dict[int, list[int]] = {}
    for value in accumulator_targets:
        starts_at.setdefault(first_bit[value], []).append(value)

    accumulators: dict[int, int] = {}
    current_power_register = one_register

    for bit in range(highest_bit + 1):
        # Extend accumulators that were started on an earlier bit.
        completing = []
        for target, accumulator in sorted(accumulators.items()):
            if target >> bit & 1:
                instructions.append(
                    ["+", accumulator, current_power_register, accumulator]
                )
                if bit == last_bit[target]:
                    completing.append(target)
        for target in completing:
            heapq.heappush(free_registers, accumulators.pop(target))

        new_targets = list(starts_at.get(bit, ()))
        captured_power = False

        # From bit 1 onward the power register is not the preserved constant 1.
        # One new accumulator can take ownership of it for free.  The next power
        # is then written to another available register.
        if bit >= 1 and new_targets:
            capture = min(new_targets, key=lambda value: (last_bit[value], value))
            accumulators[capture] = current_power_register
            new_targets.remove(capture)
            captured_power = True

        # Other targets beginning on this bit need an explicit copy.  Multiplying
        # by the preserved constant 1 is a legal one-instruction copy.
        for target in new_targets:
            if not free_registers:
                raise RuntimeError(f"{puzzle.puzzle_id}: exhausted registers")
            destination = heapq.heappop(free_registers)
            instructions.append(
                ["*", current_power_register, one_register, destination]
            )
            accumulators[target] = destination

        if bit == highest_bit:
            break

        if bit == 0 or captured_power:
            if not free_registers:
                raise RuntimeError(f"{puzzle.puzzle_id}: no register for next power")
            next_power_register = heapq.heappop(free_registers)
        else:
            next_power_register = current_power_register
        instructions.append(
            ["+", current_power_register, current_power_register, next_power_register]
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
    candidate_lengths = {}

    for puzzle in puzzles:
        candidate = solve_power_basis(puzzle)
        validate_program(puzzle, candidate)
        candidate_length = len(candidate)
        current_length = len(current_programs[puzzle.puzzle_id])
        candidate_total += candidate_length
        candidate_lengths[puzzle.puzzle_id] = candidate_length
        if candidate_length < current_length:
            selected_programs[puzzle.puzzle_id] = candidate
            improved_rows.append(
                {
                    "id": puzzle.puzzle_id,
                    "current_instructions": current_length,
                    "power_basis_instructions": candidate_length,
                    "improvement": current_length - candidate_length,
                    "targets": len(puzzle.targets),
                    "starting_values": len(puzzle.starting_values),
                    "maximum_target_bits": max(puzzle.targets).bit_length(),
                }
            )

    for puzzle_id in order:
        validate_program(puzzle_by_id[puzzle_id], selected_programs[puzzle_id])
    write_submission(args.output, order, selected_programs)

    selected_total = sum(len(program) for program in selected_programs.values())
    improvement_values = [row["improvement"] for row in improved_rows]
    report = {
        "solver": "shared_streaming_power_basis",
        "current_submission": str(args.current),
        "output_submission": str(args.output),
        "puzzles": len(puzzles),
        "improved_puzzles": len(improved_rows),
        "unchanged_puzzles": len(puzzles) - len(improved_rows),
        "current_score": current_total,
        "all_power_basis_score": candidate_total,
        "selected_score": selected_total,
        "total_improvement": current_total - selected_total,
        "improvement_summary": {
            "maximum": max(improvement_values, default=0),
            "mean_over_improved": (
                sum(improvement_values) / len(improvement_values)
                if improvement_values
                else 0.0
            ),
        },
        "candidate_length_histogram": dict(
            sorted(Counter(candidate_lengths.values()).items())
        ),
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
                "all_power_basis_score": candidate_total,
                "selected_score": selected_total,
                "improvement": current_total - selected_total,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
