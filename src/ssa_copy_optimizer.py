#!/usr/bin/env python3
"""SSA copy propagation, dead-code elimination and register reassignment.

This conservative companion to ``value_graph_optimizer`` preserves distinct
computations that merely happen to have the same numeric value.  It aliases
only true identity instructions (for example ``x * 1``), so its live-register
pressure cannot exceed the original program's pressure.
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
from value_graph_optimizer import execute


@dataclass(frozen=True)
class Node:
    operator: str
    left: int
    right: int
    value: int
    order: int


def build_ssa(puzzle: Puzzle, program: list[Instruction]):
    register_nodes: list[int | None] = [None] * puzzle.registers
    node_values: dict[int, int] = {}
    initial_nodes = set()
    next_initial = -1
    for register, value in enumerate(puzzle.starting_values):
        node = next_initial
        next_initial -= 1
        register_nodes[register] = node
        node_values[node] = value
        initial_nodes.add(node)

    nodes: dict[int, Node] = {}
    target_occurrences: dict[int, list[int]] = {target: [] for target in puzzle.targets}
    initial_targets = set(puzzle.starting_values) & set(puzzle.targets)
    identities = 0

    for order, (operator, left_register, right_register, destination) in enumerate(
        program
    ):
        left_node = register_nodes[left_register]
        right_node = register_nodes[right_register]
        assert left_node is not None and right_node is not None
        left_value = node_values[left_node]
        right_value = node_values[right_node]
        result = execute(operator, left_value, right_value)

        alias = None
        if result == left_value:
            alias = left_node
        elif result == right_value:
            alias = right_node

        if alias is not None:
            result_node = alias
            identities += 1
        else:
            result_node = order
            nodes[result_node] = Node(
                operator, left_node, right_node, result, order
            )
            node_values[result_node] = result
        register_nodes[destination] = result_node
        if result in target_occurrences and result not in initial_targets:
            target_occurrences[result].append(result_node)

    return nodes, node_values, initial_nodes, initial_targets, target_occurrences, identities


def select_required_nodes(
    puzzle: Puzzle,
    nodes: dict[int, Node],
    initial_nodes: set[int],
    initial_targets: set[int],
    target_occurrences: dict[int, list[int]],
) -> set[int]:
    selected = []
    for target in puzzle.targets:
        if target in initial_targets:
            continue
        occurrences = target_occurrences[target]
        if not occurrences:
            raise RuntimeError(f"{puzzle.puzzle_id}: target {target} has no SSA occurrence")
        # Earliest coverage normally has the smallest already-built dependency
        # cone and permits everything after the final target to be discarded.
        selected.append(occurrences[0])

    required = set()
    stack = list(selected)
    while stack:
        node = stack.pop()
        if node in initial_nodes or node in required:
            continue
        required.add(node)
        recipe = nodes[node]
        stack.append(recipe.left)
        stack.append(recipe.right)
    return required


def emit_ssa(
    puzzle: Puzzle,
    nodes: dict[int, Node],
    node_values: dict[int, int],
    required: set[int],
) -> list[Instruction]:
    ordered = sorted(required, key=lambda node: nodes[node].order)
    uses = Counter()
    for node in ordered:
        uses[nodes[node].left] += 1
        uses[nodes[node].right] += 1

    node_register: dict[int, int] = {}
    occupied = set()
    for register in range(len(puzzle.starting_values)):
        initial_node = -1 - register
        if uses[initial_node]:
            node_register[initial_node] = register
            occupied.add(register)
    free = list(set(range(puzzle.registers)) - occupied)
    heapq.heapify(free)

    emitted: list[Instruction] = []
    for node in ordered:
        recipe = nodes[node]
        left_register = node_register[recipe.left]
        right_register = node_register[recipe.right]
        multiplicity = Counter((recipe.left, recipe.right))
        dying = [
            source
            for source, count in multiplicity.items()
            if uses[source] == count
        ]
        if dying:
            destination = node_register[dying[0]]
        elif free:
            destination = heapq.heappop(free)
        else:
            raise RuntimeError(f"{puzzle.puzzle_id}: SSA allocation exceeds registers")

        emitted.append(
            [recipe.operator, left_register, right_register, destination]
        )
        for source, count in multiplicity.items():
            uses[source] -= count
            if uses[source] == 0:
                old_register = node_register.pop(source)
                if old_register != destination:
                    heapq.heappush(free, old_register)

        if uses[node]:
            node_register[node] = destination
        else:
            heapq.heappush(free, destination)
    return emitted


def optimize_program(puzzle: Puzzle, program: list[Instruction]):
    (
        nodes,
        node_values,
        initial_nodes,
        initial_targets,
        target_occurrences,
        identities,
    ) = build_ssa(puzzle, program)
    required = select_required_nodes(
        puzzle, nodes, initial_nodes, initial_targets, target_occurrences
    )
    optimized = emit_ssa(puzzle, nodes, node_values, required)
    return optimized, {
        "identity_instructions": identities,
        "removed_instructions": len(program) - len(optimized),
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
    failures = 0
    improved_rows = []

    for puzzle in puzzles:
        current = current_programs[puzzle.puzzle_id]
        try:
            candidate, metadata = optimize_program(puzzle, current)
            validate_program(puzzle, candidate)
        except RuntimeError:
            failures += 1
            continue
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
        "optimizer": "ssa_identity_propagation_dce_liveness_allocation",
        "current_submission": str(args.current),
        "output_submission": str(args.output),
        "current_score": current_total,
        "selected_score": selected_total,
        "allocation_failures": failures,
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
                "allocation_failures": failures,
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
