#!/usr/bin/env python3
"""Hybrid per-target planner for Santa 2026.

For every missing target, the planner considers direct construction,
anchor/difference, factor/quotient and exact-division alternatives.  A local
facility search chooses combinations that share components.  The components
are built through recursive anchors, then both phase-2 graph optimizers are
applied before the candidate is compared with the current submission.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from math import gcd
from pathlib import Path

from anchor_difference_solver import (
    build_retained_components,
    choose_anchor_plan,
    digit_weight,
)
from recursive_anchor_solver import materialize_retained_values, plan_components
from ssa_copy_optimizer import optimize_program as optimize_ssa
from tiny_solver import (
    Instruction,
    Puzzle,
    load_puzzles,
    read_submission,
    validate_program,
    write_submission,
)
from value_graph_optimizer import optimize_program as optimize_values


@dataclass(frozen=True)
class Alternative:
    operator: str | None
    left: int
    right: int | None
    raw_cost: int
    kind: str

    @property
    def components(self) -> tuple[int, ...]:
        if self.operator is None:
            return (self.left,)
        assert self.right is not None
        return (self.left, self.right)


def add_alternative(
    choices: dict[tuple[str | None, int, int | None], Alternative],
    alternative: Alternative,
) -> None:
    key = (alternative.operator, alternative.left, alternative.right)
    previous = choices.get(key)
    if previous is None or alternative.raw_cost < previous.raw_cost:
        choices[key] = alternative


def target_alternatives(
    puzzle: Puzzle,
) -> tuple[list[int], list[list[Alternative]], dict[int, Alternative]]:
    targets = sorted(set(puzzle.targets) - set(puzzle.starting_values))
    additive_plan = choose_anchor_plan(puzzle)
    all_alternatives: list[list[Alternative]] = []
    preferred_additive: dict[int, Alternative] = {}
    starts = set(puzzle.starting_values)

    for target in targets:
        direct_cost = digit_weight(target, puzzle.value_limit)
        choices: dict[tuple[str | None, int, int | None], Alternative] = {}
        direct = Alternative(None, target, None, direct_cost, "direct")
        add_alternative(choices, direct)

        assignment = additive_plan.get(target)
        if assignment is not None:
            anchor, delta = assignment
            operator = "+" if target > anchor else "-"
            additive = Alternative(
                operator,
                anchor,
                delta,
                digit_weight(delta, puzzle.value_limit) + 1,
                "anchor",
            )
            add_alternative(choices, additive)
            preferred_additive[target] = additive

        # Other targets are possible anchors.  Keeping only alternatives near
        # the direct digit cost prevents the local search from being flooded by
        # relations that cannot repay their extra component.
        for anchor in targets:
            if anchor == target:
                continue
            delta = abs(target - anchor)
            cost = digit_weight(delta, puzzle.value_limit) + 1
            if cost <= direct_cost + 1:
                operator = "+" if target > anchor else "-"
                add_alternative(
                    choices,
                    Alternative(operator, anchor, delta, cost, "anchor"),
                )

        factor_candidates = {value for value in starts if value > 1}
        for other in targets:
            if other != target:
                common = gcd(target, other)
                if common > 1:
                    factor_candidates.add(common)
        for factor in factor_candidates:
            if target % factor:
                continue
            quotient = target // factor
            if quotient <= 1:
                continue
            cost = digit_weight(quotient, puzzle.value_limit) + 1
            if cost <= direct_cost + 1:
                add_alternative(
                    choices,
                    Alternative("*", factor, quotient, cost, "factor"),
                )

        # If a larger target is an exact multiple, the smaller one can be
        # covered by dividing a shared numerator by a compact quotient.
        for numerator in targets:
            if numerator <= target or numerator % target:
                continue
            divisor = numerator // target
            cost = digit_weight(divisor, puzzle.value_limit) + 1
            if cost <= direct_cost + 1:
                add_alternative(
                    choices,
                    Alternative("/", numerator, divisor, cost, "division"),
                )

        ranked = sorted(
            choices.values(),
            key=lambda alt: (alt.raw_cost, alt.kind != "direct", alt.components),
        )
        kept = [direct]
        for alternative in ranked:
            if alternative != direct and alternative not in kept:
                kept.append(alternative)
            if len(kept) >= 8:
                break
        if target in preferred_additive and preferred_additive[target] not in kept:
            kept[-1] = preferred_additive[target]
        all_alternatives.append(kept)

    return targets, all_alternatives, preferred_additive


def state_components(
    state: tuple[int, ...], alternatives: list[list[Alternative]]
) -> set[int]:
    components = set()
    for choice, options in zip(state, alternatives):
        components.update(options[choice].components)
    return components


def estimate_state(
    puzzle: Puzzle,
    targets: list[int],
    alternatives: list[list[Alternative]],
    state: tuple[int, ...],
) -> int:
    components = state_components(state, alternatives)
    starts = set(puzzle.starting_values)
    occupied = components | starts
    if len(occupied) >= puzzle.registers:
        return 10**12 + len(occupied)

    noninitial = components - starts
    if noninitial:
        weights = [digit_weight(value, puzzle.value_limit) for value in noninitial]
        highest = max(value.bit_length() for value in noninitial)
        component_cost = 2 * highest + len(noninitial) + sum(
            max(0, weight - 1) for weight in weights
        )
    else:
        component_cost = 0

    final_operations = 0
    for target, choice, options in zip(targets, state, alternatives):
        alternative = options[choice]
        if alternative.operator is not None and target not in components:
            final_operations += 1
    return component_cost + final_operations


def additive_seed(
    targets: list[int],
    alternatives: list[list[Alternative]],
    preferred: dict[int, Alternative],
) -> tuple[int, ...]:
    state = []
    for target, options in zip(targets, alternatives):
        wanted = preferred.get(target)
        state.append(options.index(wanted) if wanted in options else 0)
    return tuple(state)


def improve_state(
    puzzle: Puzzle,
    targets: list[int],
    alternatives: list[list[Alternative]],
    seed: tuple[int, ...],
    cache: dict[tuple[int, ...], int],
) -> tuple[int, ...]:
    def cost(state: tuple[int, ...]) -> int:
        if state not in cache:
            cache[state] = estimate_state(puzzle, targets, alternatives, state)
        return cache[state]

    current = seed
    for _ in range(7):
        best = current
        best_cost = cost(current)
        for position, options in enumerate(alternatives):
            for choice in range(len(options)):
                if choice == current[position]:
                    continue
                candidate = current[:position] + (choice,) + current[position + 1 :]
                candidate_cost = cost(candidate)
                if (candidate_cost, candidate) < (best_cost, best):
                    best = candidate
                    best_cost = candidate_cost
        if best == current:
            break
        current = best
    return current


def search_states(
    puzzle: Puzzle,
    targets: list[int],
    alternatives: list[list[Alternative]],
    preferred: dict[int, Alternative],
) -> list[tuple[int, ...]]:
    if not targets:
        return [()]
    direct = tuple(0 for _ in targets)
    cheapest = tuple(
        min(range(len(options)), key=lambda index: (options[index].raw_cost, index))
        for options in alternatives
    )
    additive = additive_seed(targets, alternatives, preferred)
    cache: dict[tuple[int, ...], int] = {}
    candidates = {direct, cheapest, additive}
    candidates.update(
        improve_state(puzzle, targets, alternatives, seed, cache)
        for seed in tuple(candidates)
    )

    # A small beam around the local optima captures paired changes where one
    # component becomes worthwhile only after a second target starts sharing it.
    beam = sorted(candidates, key=lambda state: (estimate_state(
        puzzle, targets, alternatives, state
    ), state))[:4]
    for _ in range(2):
        neighbors = set(beam)
        for state in beam:
            for position, options in enumerate(alternatives):
                for choice in range(len(options)):
                    if choice != state[position]:
                        neighbors.add(
                            state[:position] + (choice,) + state[position + 1 :]
                        )
        beam = sorted(
            neighbors,
            key=lambda state: (
                cache.setdefault(
                    state, estimate_state(puzzle, targets, alternatives, state)
                ),
                state,
            ),
        )[:4]
    candidates.update(beam)
    return sorted(
        candidates,
        key=lambda state: (
            cache.setdefault(state, estimate_state(puzzle, targets, alternatives, state)),
            state,
        ),
    )[:3]


def build_hybrid_program(
    puzzle: Puzzle,
    targets: list[int],
    alternatives: list[list[Alternative]],
    state: tuple[int, ...],
    inner_depth: int,
) -> list[Instruction]:
    selected = [options[choice] for choice, options in zip(state, alternatives)]
    components = set(value for alternative in selected for value in alternative.components)
    starts = set(puzzle.starting_values)

    plans = []
    required_sets = []
    required = set(components)
    for _ in range(inner_depth):
        layer_puzzle = Puzzle(
            puzzle_id=puzzle.puzzle_id,
            starting_values=puzzle.starting_values,
            targets=tuple(sorted(required)),
            value_limit=puzzle.value_limit,
            registers=puzzle.registers,
        )
        plan = choose_anchor_plan(layer_puzzle)
        plans.append(plan)
        required_sets.append(required)
        required = plan_components(plan)

    if required:
        instructions, registers = build_retained_components(puzzle, required)
    else:
        instructions, registers = [], {}
    for register, value in enumerate(puzzle.starting_values):
        registers.setdefault(value, register)

    for level in range(len(plans) - 1, -1, -1):
        retained = required_sets[level] | starts
        registers = materialize_retained_values(
            puzzle,
            retained,
            plans[level],
            instructions,
            dict(registers),
        )

    component_registers = {
        value: register for value, register in registers.items() if value in components
    }
    if set(component_registers) != components:
        raise RuntimeError(f"{puzzle.puzzle_id}: hybrid components missing")

    scratch_candidates = sorted(
        set(range(puzzle.registers)) - set(component_registers.values())
    )
    pending = [
        (target, alternative)
        for target, alternative in zip(targets, selected)
        if alternative.operator is not None and target not in component_registers
    ]
    if pending and not scratch_candidates:
        raise RuntimeError(f"{puzzle.puzzle_id}: hybrid scratch register unavailable")
    scratch = scratch_candidates[0] if scratch_candidates else 0
    for _, alternative in pending:
        assert alternative.right is not None and alternative.operator is not None
        instructions.append(
            [
                alternative.operator,
                component_registers[alternative.left],
                component_registers[alternative.right],
                scratch,
            ]
        )
    return instructions


def post_optimize(puzzle: Puzzle, program: list[Instruction]) -> list[Instruction]:
    best = program
    try:
        value_candidate, _ = optimize_values(puzzle, best)
        validate_program(puzzle, value_candidate)
        if len(value_candidate) < len(best):
            best = value_candidate
    except RuntimeError:
        pass
    ssa_candidate, _ = optimize_ssa(puzzle, best)
    validate_program(puzzle, ssa_candidate)
    if len(ssa_candidate) < len(best):
        best = ssa_candidate
    return best


def solve_hybrid(puzzle: Puzzle):
    targets, alternatives, preferred = target_alternatives(puzzle)
    if not targets:
        return [], {"relations": {}, "inner_depth": 0, "states_tested": 1}
    states = search_states(puzzle, targets, alternatives, preferred)
    best = None
    best_metadata = None
    for state in states:
        for depth in (2, 3):
            try:
                candidate = build_hybrid_program(
                    puzzle, targets, alternatives, state, depth
                )
                validate_program(puzzle, candidate)
                candidate = post_optimize(puzzle, candidate)
            except (RuntimeError, AssertionError, KeyError, ValueError):
                continue
            if best is None or len(candidate) < len(best):
                kinds = {}
                for choice, options in zip(state, alternatives):
                    kind = options[choice].kind
                    kinds[kind] = kinds.get(kind, 0) + 1
                best = candidate
                best_metadata = {
                    "relations": kinds,
                    "inner_depth": depth,
                    "states_tested": len(states),
                }
    return best, best_metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int)
    args = parser.parse_args()

    puzzles = load_puzzles(args.puzzles)
    order, current_programs = read_submission(args.current)
    puzzle_by_id = {puzzle.puzzle_id: puzzle for puzzle in puzzles}
    selected_programs = dict(current_programs)
    current_total = sum(len(program) for program in current_programs.values())
    candidates = 0
    failures = 0
    improved_rows = []

    end_index = args.end_index if args.end_index is not None else len(puzzles)
    selected_puzzles = puzzles[args.start_index:end_index]
    for puzzle in selected_puzzles:
        candidate, metadata = solve_hybrid(puzzle)
        if candidate is None:
            failures += 1
            continue
        validate_program(puzzle, candidate)
        candidates += 1
        current = current_programs[puzzle.puzzle_id]
        if len(candidate) < len(current):
            selected_programs[puzzle.puzzle_id] = candidate
            improved_rows.append(
                {
                    "id": puzzle.puzzle_id,
                    "current_instructions": len(current),
                    "hybrid_instructions": len(candidate),
                    "improvement": len(current) - len(candidate),
                    **(metadata or {}),
                }
            )

    for puzzle_id in order:
        validate_program(puzzle_by_id[puzzle_id], selected_programs[puzzle_id])
    write_submission(args.output, order, selected_programs)
    selected_total = sum(len(program) for program in selected_programs.values())

    report = {
        "solver": "hybrid_per_target_facility_local_beam_search",
        "current_submission": str(args.current),
        "output_submission": str(args.output),
        "current_score": current_total,
        "selected_score": selected_total,
        "start_index": args.start_index,
        "end_index": end_index,
        "candidate_puzzles": candidates,
        "failed_puzzles": failures,
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
                "failed_puzzles": failures,
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
