#!/usr/bin/env python3
"""Anchor-and-difference solver for Santa 2026.

Nearby targets are represented as anchor +/- small delta.  The set of anchors
and deltas is built jointly with signed digits and retained in registers; final
targets then cost one arithmetic instruction each.
"""

from __future__ import annotations

import argparse
import heapq
import json
from pathlib import Path

from signed_digit_solver import choose_digits
from tiny_solver import (
    Instruction,
    Puzzle,
    load_puzzles,
    read_submission,
    validate_program,
    write_submission,
)


def digit_weight(value: int, value_limit: int) -> int:
    return len(choose_digits(value, value_limit))


def choose_anchor_plan(puzzle: Puzzle) -> dict[int, tuple[int, int] | None]:
    """Map each missing target to None (direct) or (anchor, positive delta)."""
    missing = set(puzzle.targets) - set(puzzle.starting_values)
    plan: dict[int, tuple[int, int] | None] = {}
    remaining = set(missing)

    # Starting values are free anchors.  Use one only when it strictly reduces
    # the estimated signed-digit work after paying for the final combination.
    for target in sorted(list(remaining)):
        direct_cost = digit_weight(target, puzzle.value_limit)
        options = []
        for anchor in set(puzzle.starting_values):
            if anchor == target:
                continue
            delta = abs(target - anchor)
            if delta == 0:
                continue
            cost = digit_weight(delta, puzzle.value_limit) + 1
            options.append((cost, delta, anchor))
        if options:
            cost, delta, anchor = min(options)
            if cost < direct_cost:
                plan[target] = (anchor, delta)
                remaining.remove(target)

    # Greedy facility-location step.  Opening an anchor means building that
    # target directly; related targets are assigned only when their delta plus
    # final operation is cheaper than their own direct digit representation.
    while remaining:
        best = None
        for anchor in sorted(remaining):
            assignments = []
            total_saving = 0
            for target in sorted(remaining):
                if target == anchor:
                    continue
                delta = abs(target - anchor)
                direct_cost = digit_weight(target, puzzle.value_limit)
                derived_cost = digit_weight(delta, puzzle.value_limit) + 1
                saving = direct_cost - derived_cost
                if saving > 0:
                    assignments.append((target, delta, saving))
                    total_saving += saving
            candidate = (total_saving, len(assignments), -anchor, anchor, assignments)
            if best is None or candidate > best:
                best = candidate

        assert best is not None
        total_saving, _, _, anchor, assignments = best
        if total_saving <= 0:
            for target in remaining:
                plan[target] = None
            break

        plan[anchor] = None
        remaining.remove(anchor)
        for target, delta, _ in assignments:
            if target in remaining:
                plan[target] = (anchor, delta)
                remaining.remove(target)

    return plan


def build_retained_components(
    puzzle: Puzzle, components: set[int]
) -> tuple[list[Instruction], dict[int, int]]:
    """Build all components and keep one live register for every value."""
    instructions: list[Instruction] = []
    component_registers: dict[int, int] = {}
    for index, value in enumerate(puzzle.starting_values):
        if value in components:
            component_registers.setdefault(value, index)

    free_registers = list(range(len(puzzle.starting_values), puzzle.registers))
    heapq.heapify(free_registers)

    one_register = next(
        (index for index, value in enumerate(puzzle.starting_values) if value == 1),
        None,
    )
    if one_register is None:
        one_register = heapq.heappop(free_registers)
        instructions.append(["/", 0, 0, one_register])
    if 1 in components:
        component_registers[1] = one_register

    remaining = components - set(component_registers)
    if not remaining:
        return instructions, component_registers

    two_register = next(
        (index for index, value in enumerate(puzzle.starting_values) if value == 2),
        None,
    )
    if two_register is None:
        two_register = heapq.heappop(free_registers)
        instructions.append(["+", one_register, one_register, two_register])
    if 2 in components:
        component_registers[2] = two_register
        remaining.discard(2)
    if not remaining:
        return instructions, component_registers

    representations = {
        value: choose_digits(value, puzzle.value_limit) for value in remaining
    }
    highest_bit = max(max(digits) for digits in representations.values())
    current_power_register = two_register
    for bit in range(2, highest_bit + 1):
        if bit == 2:
            current_power_register = heapq.heappop(free_registers)
        source = two_register if bit == 2 else current_power_register
        instructions.append(["+", source, source, current_power_register])

    starts_at: dict[int, list[int]] = {}
    ends_at = {}
    for value, digits in representations.items():
        starts_at.setdefault(max(digits), []).append(value)
        ends_at[value] = min(digits)
    lowest_bit = min(ends_at.values())
    active: dict[int, int] = {}

    for bit in range(highest_bit, lowest_bit - 1, -1):
        completing = []
        for value, accumulator in sorted(active.items()):
            digit = representations[value].get(bit, 0)
            if digit == 1:
                instructions.append(
                    ["+", accumulator, current_power_register, accumulator]
                )
            elif digit == -1:
                instructions.append(
                    ["-", accumulator, current_power_register, accumulator]
                )
            if digit and bit == ends_at[value]:
                completing.append(value)
        for value in completing:
            component_registers[value] = active.pop(value)

        new_values = list(starts_at.get(bit, ()))
        captured_power = False
        if new_values and current_power_register != one_register:
            capture = min(new_values, key=lambda value: (ends_at[value], value))
            if ends_at[capture] == bit:
                component_registers[capture] = current_power_register
            else:
                active[capture] = current_power_register
            new_values.remove(capture)
            captured_power = True

        for value in new_values:
            if not free_registers:
                raise RuntimeError(f"{puzzle.puzzle_id}: exhausted registers")
            destination = heapq.heappop(free_registers)
            instructions.append(
                ["*", current_power_register, one_register, destination]
            )
            if ends_at[value] == bit:
                component_registers[value] = destination
            else:
                active[value] = destination

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

    if active or set(component_registers) != components:
        missing = components - set(component_registers)
        raise AssertionError(
            f"{puzzle.puzzle_id}: unfinished components {sorted(missing)}"
        )
    return instructions, component_registers


def solve_anchor_differences(puzzle: Puzzle) -> tuple[list[Instruction], dict]:
    plan = choose_anchor_plan(puzzle)
    components = set()
    derived = []
    for target, assignment in plan.items():
        if assignment is None:
            components.add(target)
        else:
            anchor, delta = assignment
            components.add(anchor)
            components.add(delta)
            derived.append((target, anchor, delta))

    instructions, component_registers = build_retained_components(puzzle, components)
    scratch_candidates = sorted(set(range(puzzle.registers)) - set(component_registers.values()))
    if derived and not scratch_candidates:
        raise RuntimeError(f"{puzzle.puzzle_id}: no scratch register for combinations")
    scratch = scratch_candidates[0] if scratch_candidates else 0

    for target, anchor, delta in sorted(derived):
        if target > anchor:
            instructions.append(
                ["+", component_registers[anchor], component_registers[delta], scratch]
            )
        else:
            instructions.append(
                ["-", component_registers[anchor], component_registers[delta], scratch]
            )

    metadata = {
        "direct_targets": sum(assignment is None for assignment in plan.values()),
        "derived_targets": len(derived),
        "components": len(components),
    }
    return instructions, metadata


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

    for puzzle in puzzles:
        candidate, metadata = solve_anchor_differences(puzzle)
        validate_program(puzzle, candidate)
        candidate_length = len(candidate)
        candidate_total += candidate_length
        current_length = len(current_programs[puzzle.puzzle_id])
        if candidate_length < current_length:
            selected_programs[puzzle.puzzle_id] = candidate
            improved_rows.append(
                {
                    "id": puzzle.puzzle_id,
                    "current_instructions": current_length,
                    "anchor_instructions": candidate_length,
                    "improvement": current_length - candidate_length,
                    **metadata,
                }
            )

    for puzzle_id in order:
        validate_program(puzzle_by_id[puzzle_id], selected_programs[puzzle_id])
    write_submission(args.output, order, selected_programs)
    selected_total = sum(len(program) for program in selected_programs.values())

    report = {
        "solver": "anchor_and_difference",
        "current_submission": str(args.current),
        "output_submission": str(args.output),
        "current_score": current_total,
        "all_anchor_score": candidate_total,
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
                "improved_puzzles": len(improved_rows),
                "current_score": current_total,
                "all_anchor_score": candidate_total,
                "selected_score": selected_total,
                "improvement": current_total - selected_total,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
