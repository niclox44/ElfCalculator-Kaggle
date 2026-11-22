"""Bounded synthesis of one-, two-, and three-operation SSA replacements.

The grammar includes new intermediates in chains and independent branches.
It is deliberately bounded, not a proof of optimality. Numeric
operations are exact; output and transient-target roots are preserved.
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
from math import isqrt
import time

from ssa_copy_optimizer import Node, build_ssa, emit_ssa, select_required_nodes
from tiny_solver import validate_program
from value_graph_optimizer import execute


def one_step_recipes(available, limit):
    """One legal recipe per newly reachable value; no free constants."""
    recipes = {}
    values = sorted(available)
    for i, a in enumerate(values):
        for b in values[i:]:
            for op, x, y, result in (("+", a, b, a + b),
                                     ("*", a, b, a * b),
                                     ("-", b, a, b - a)):
                if 0 < result <= limit and result not in available:
                    recipes.setdefault(result, (op, x, y, result))
            if b % a == 0:
                result = b // a
                if result <= limit and result not in available:
                    recipes.setdefault(result, ("/", b, a, result))
    return recipes


def inverse_partners(target, known, limit):
    """Yield (missing operand, operator, left, right) for an exact result."""
    for missing, op, left, right in (
        (target - known, "+", known, target - known),
        (known - target, "-", known, known - target),
        (target + known, "-", target + known, known),
        (target * known, "/", target * known, known),
    ):
        if 0 < missing <= limit:
            yield missing, op, left, right
    if target % known == 0:
        yield target // known, "*", known, target // known
    if known % target == 0:
        yield known // target, "/", known, known // target


def short_programs(target, available, limit, max_ops=3, candidate_limit=16):
    """Enumerate bounded expression shapes using one-step meet-in-the-middle.

    Three-operation candidates cover chains and independent branches. Two-operation
    candidates also cover squaring or doubling a newly computed intermediate.
    Keeping one recipe per intermediate and capping candidates are heuristics.
    """
    first = one_step_recipes(available, limit)
    seen = set()
    emitted = 0

    def unique(program):
        nonlocal emitted
        key = tuple(program)
        if key in seen:
            return False
        seen.add(key)
        emitted += 1
        return True

    if target in first:
        yield [first[target]]
        return
    if max_ops < 2:
        return
    # A final operation with one old and one newly synthesized operand.
    for value in sorted(available):
        for missing, op, left, right in inverse_partners(target, value, limit):
            if missing in first and missing != target:
                program = [first[missing], (op, left, right, target)]
                if unique(program):
                    yield program
                    if emitted >= candidate_limit:
                        return
    for intermediate, op in ((target // 2 if target % 2 == 0 else 0, "+"),
                             (isqrt(target) if isqrt(target) ** 2 == target else 0, "*")):
        if intermediate in first and intermediate != target:
            program = [first[intermediate], (op, intermediate, intermediate, target)]
            if unique(program):
                yield program
                if emitted >= candidate_limit:
                    return
    if emitted or max_ops < 3:
        return
    # A three-operation chain, working backwards from the last old operand.
    for last in sorted(available):
        for middle, final_op, final_left, final_right in inverse_partners(target, last, limit):
            if middle in available or middle == target:
                continue
            for old in sorted(available):
                for intermediate, op, left, right in inverse_partners(middle, old, limit):
                    if intermediate in first and intermediate not in (target, middle):
                        program = [first[intermediate], (op, left, right, middle),
                                   (final_op, final_left, final_right, target)]
                        if unique(program):
                            yield program
                            if emitted >= candidate_limit:
                                return
    # Two independent newly computed operands followed by their combination.
    for value in sorted(first):
        if value == target:
            continue
        for missing, op, left, right in inverse_partners(target, value, limit):
            if missing in first and missing not in (target, value):
                program = [first[value], first[missing], (op, left, right, target)]
                if unique(program):
                    yield program
                    if emitted >= candidate_limit:
                        return


def private_cone(root, nodes, uses, protected, max_nodes=6):
    """Remove up to max_nodes exclusive producers, keeping other output roots."""
    removed = {root}
    decrements = Counter()
    stack = [root]
    while stack:
        current = stack.pop()
        recipe = nodes[current]
        for operand in (recipe.left, recipe.right):
            decrements[operand] += 1
            if (operand in nodes and operand not in removed and operand not in protected
                    and decrements[operand] == uses[operand] and len(removed) < max_nodes):
                removed.add(operand)
                stack.append(operand)
    return removed


def available_snapshots(puzzle, program, nodes, values):
    registers = [-1 - i for i in range(len(puzzle.starting_values))]
    registers += [None] * (puzzle.registers - len(registers))
    snapshots = {}
    for index, (op, a, b, destination) in enumerate(program):
        left, right = registers[a], registers[b]
        result = execute(op, values[left], values[right])
        snapshots[index] = tuple(n for n in registers if n is not None)
        if index in nodes:
            registers[destination] = index
        else:
            registers[destination] = left if result == values[left] else right
    return snapshots


def optimize_short(puzzle, program, max_windows=96, max_inputs=16, passes=2,
                   deadline=None, max_new_ops=3):
    best = program
    metadata = {"synthesis_windows": 0, "synthesis_candidates": 0,
                "synthesis_rewrites": 0, "synthesis_allocation_failures": 0,
                "synthesis_saved": 0, "synthesis_new_intermediates": 0,
                "synthesis_budget_exhausted": False}
    for _ in range(passes):
        if deadline is not None and time.process_time() >= deadline:
            metadata["synthesis_budget_exhausted"] = True
            break
        nodes, values, initial, initial_targets, occurrences, _ = build_ssa(puzzle, best)
        snapshots = available_snapshots(puzzle, best, nodes, values)
        roots = {occurrences[t][0] for t in puzzle.targets if t not in initial_targets}
        live = select_required_nodes(puzzle, nodes, initial, initial_targets, occurrences)
        next_node = max(nodes, default=-1) + 1
        before = len(best)
        for root in sorted(live, reverse=True):
            if (metadata["synthesis_windows"] >= max_windows
                    or (deadline is not None and time.process_time() >= deadline)):
                metadata["synthesis_budget_exhausted"] = True
                break
            if root not in live or root not in snapshots:
                continue
            uses = Counter()
            for node in live:
                uses.update((nodes[node].left, nodes[node].right))
            cone = private_cone(root, nodes, uses, roots - {root})
            if len(cone) < 3:
                continue
            boundary = {source for n in cone for source in (nodes[n].left, nodes[n].right)
                        if source not in cone}
            # Include old registers to allow unrelated but useful constants.
            # Only existing live nodes can be reused without reviving dead code.
            extra = [n for n in snapshots[root] if n not in cone and (n in live or n in initial)]
            available = {}
            for node in sorted(boundary, key=lambda n: (values[n], n)):
                available.setdefault(values[node], node)
            for node in sorted(extra, key=lambda n: (values[n], n)):
                if len(available) >= max_inputs:
                    break
                available.setdefault(values[node], node)
            if len(available) > max_inputs:
                continue
            metadata["synthesis_windows"] += 1
            target = values[root]
            for replacement in short_programs(target, available, puzzle.value_limit,
                                               min(max_new_ops, len(cone) - 1)):
                if deadline is not None and time.process_time() >= deadline:
                    metadata["synthesis_budget_exhausted"] = True
                    break
                metadata["synthesis_candidates"] += 1
                trial_nodes = {n: node for n, node in nodes.items() if n not in cone or n == root}
                trial_values = dict(values)
                locations = dict(available)
                source_order = max((nodes[n].order for n in available.values() if n in nodes), default=-1)
                root_order = nodes[root].order
                for step, (op, left, right, result) in enumerate(replacement):
                    node_id = root if step == len(replacement) - 1 else next_node + step
                    order = Fraction(source_order) + (Fraction(root_order) - source_order) * Fraction(step + 1, len(replacement))
                    trial_nodes[node_id] = Node(op, locations[left], locations[right], result, order)
                    trial_values[node_id] = result
                    locations[result] = node_id
                trial_live = select_required_nodes(
                    puzzle, trial_nodes, initial, initial_targets, occurrences)
                try:
                    candidate = emit_ssa(puzzle, trial_nodes, trial_values, trial_live)
                except RuntimeError:
                    metadata["synthesis_allocation_failures"] += 1
                    continue
                validate_program(puzzle, candidate)
                if len(candidate) >= len(best):
                    continue
                nodes, values, live = trial_nodes, trial_values, trial_live
                next_node += len(replacement)
                metadata["synthesis_rewrites"] += 1
                metadata["synthesis_new_intermediates"] += len(replacement) - 1
                best = candidate
                break
        if len(best) == before:
            break
    metadata["synthesis_saved"] = len(program) - len(best)
    validate_program(puzzle, best)
    return best, metadata
