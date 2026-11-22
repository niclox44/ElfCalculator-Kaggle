#!/usr/bin/env python3
"""Combine numeric recipes from existing solutions and minimize shared DAGs.

Search is heuristic, with exact operation counts for each candidate DAG. Every
accepted program is scheduled into the puzzle's registers and independently
replayed. Cyclic recipes are rejected; the incumbent is always a safe fallback.
Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import heapq
import json
from pathlib import Path
import time

from tiny_solver import Puzzle, Instruction, load_puzzles, read_submission, validate_program, write_submission
from value_graph_optimizer import execute
from validate_submission import validate
from ssa_copy_optimizer import build_ssa, emit_ssa, Node, select_required_nodes


@dataclass(frozen=True, order=True)
class Recipe:
    operator: str
    left: int
    right: int

    @property
    def operands(self) -> tuple[int, ...]:
        return tuple(sorted({self.left, self.right}))


class InvalidGraph(ValueError):
    pass


def extract_recipes(puzzle: Puzzle, program: list[Instruction]):
    """Keep all nonidentity recipes, plus an acyclic first-occurrence seed."""
    validate_program(puzzle, program)
    registers = list(puzzle.starting_values) + [None] * (puzzle.registers - len(puzzle.starting_values))
    initial = set(puzzle.starting_values)
    catalog: dict[int, set[Recipe]] = defaultdict(set)
    first: dict[int, Recipe] = {}
    for op, a, b, destination in program:
        left, right = registers[a], registers[b]
        value = execute(op, left, right)
        if value not in initial and value not in (left, right):
            if op in ("+", "*"):
                left, right = sorted((left, right))
            recipe = Recipe(op, left, right)
            catalog[value].add(recipe)
            first.setdefault(value, recipe)
        registers[destination] = value
    return catalog, first


def cheapest_recipes(initial: set[int], catalog: dict[int, set[Recipe]]):
    """Dijkstra on AND/OR recipes gives an acyclic fallback, not a DAG optimum.

    Cost counts operand trees (identical operands once). It is used only for
    proposal ordering and constructing missing dependencies, never acceptance.
    """
    waiting = defaultdict(list)
    for value, recipes in catalog.items():
        for recipe in sorted(recipes):
            for operand in recipe.operands:
                waiting[operand].append((value, recipe))
    costs = {}
    chosen = {}
    queue = [(0, value, None) for value in sorted(initial)]
    heapq.heapify(queue)
    while queue:
        cost, value, recipe = heapq.heappop(queue)
        if value in costs:
            continue
        costs[value] = cost
        if recipe is not None:
            chosen[value] = recipe
        for result, candidate in waiting[value]:
            if result not in costs and all(v in costs for v in candidate.operands):
                heapq.heappush(queue, (1 + sum(costs[v] for v in candidate.operands), result, candidate))
    return chosen, costs


def close_graph(targets, initial: set[int], selected, fallback):
    """Return only live recipes in dependency order; detect cycles explicitly."""
    graph = {}
    visiting = set()
    # An iterative DFS also handles long chains without Python recursion limits.
    for target in targets:
        stack = [(target, False)]
        while stack:
            value, exiting = stack.pop()
            if value in initial or value in graph:
                continue
            recipe = selected.get(value, fallback.get(value))
            if recipe is None:
                raise InvalidGraph(f"missing recipe for {value}")
            if exiting:
                visiting.remove(value)
                graph[value] = recipe
                continue
            if value in visiting:
                raise InvalidGraph(f"cyclic recipe for {value}")
            visiting.add(value)
            stack.append((value, True))
            for operand in reversed(recipe.operands):
                stack.append((operand, False))
    return graph


def emit_graph(puzzle: Puzzle, graph: dict[int, Recipe], mode: str):
    """List scheduling with last-use register reuse and transient target coverage."""
    uses = Counter()
    children = defaultdict(list)
    pending = {}
    rank = {value: index for index, value in enumerate(graph)}
    for value, recipe in graph.items():
        uses.update(recipe.operands)
        pending[value] = sum(v in graph for v in recipe.operands)
        for operand in recipe.operands:
            children[operand].append(value)
    locations = {}
    for index, value in enumerate(puzzle.starting_values):
        if uses[value]:
            locations.setdefault(value, index)
    free = sorted(set(range(puzzle.registers)) - set(locations.values()))
    heapq.heapify(free)
    ready = {v for v, count in pending.items() if count == 0}
    program = []
    peak = len(locations)
    while ready:
        def priority(value):
            recipe = graph[value]
            dying = sum(uses[v] == 1 for v in recipe.operands)
            # A terminal target needs a temporary destination even though its
            # value can be discarded immediately after it is produced.
            impossible = not free and not dying
            delta = int(uses[value] > 0) - dying
            if mode == "pressure":
                return impossible, delta, rank[value], value
            return impossible, rank[value], delta, value

        value = min(ready, key=priority)
        recipe = graph[value]
        dying = [v for v in recipe.operands if uses[v] == 1]
        if dying:
            destination = locations[dying[0]]
        elif free:
            destination = heapq.heappop(free)
        else:
            raise InvalidGraph("register pressure exceeds puzzle limit")
        program.append([recipe.operator, locations[recipe.left], locations[recipe.right], destination])
        peak = max(peak, len(locations) + int(not dying))
        for operand in recipe.operands:
            uses[operand] -= 1
            if uses[operand] == 0:
                register = locations.pop(operand)
                if register != destination:
                    heapq.heappush(free, register)
        if uses[value]:
            locations[value] = destination
        else:
            heapq.heappush(free, destination)
        ready.remove(value)
        for child in children[value]:
            pending[child] -= 1
            if pending[child] == 0:
                ready.add(child)
    if len(program) != len(graph):
        raise InvalidGraph("cyclic or incomplete schedule")
    validate_program(puzzle, program)
    return program, peak


def emit_with_recomputation(puzzle, graph, instruction_limit):
    """Evict distant, cheap values and regenerate them from their recipes.

    Initial values are pinned because a numeric DAG need not contain recipes
    to recover them. Recursive operands are protected until their consumer runs.
    The instruction budget bounds both search time and unprofitable regeneration.
    """
    initial = set(puzzle.starting_values)
    next_uses = defaultdict(list)
    costs = {v: 0 for v in initial}
    for index, (value, recipe) in enumerate(graph.items()):
        costs[value] = 1 + sum(costs[v] for v in recipe.operands)
        for operand in recipe.operands:
            next_uses[operand].append(index)
    locations = {}
    for register, value in enumerate(puzzle.starting_values):
        if value in next_uses:
            locations.setdefault(value, register)
    free = list(set(range(puzzle.registers)) - set(locations.values()))
    heapq.heapify(free)
    program = []
    peak = len(locations)
    position = 0

    def eviction_priority(value):
        uses = next_uses[value]
        offset = bisect_right(uses, position)
        next_position = uses[offset] if offset < len(uses) else len(graph) + 1
        # Distance per reconstruction cost favors rematerializing cheap values.
        return (next_position - position) / max(1, costs[value]), next_position, -value

    def ensure(value, protected):
        nonlocal peak
        if value in locations:
            return
        if value in initial:
            raise InvalidGraph("lost initial value")
        recipe = graph[value]
        operands = sorted(recipe.operands, key=lambda v: (-costs[v], v))
        pinned = set(protected)
        for operand in operands:
            ensure(operand, pinned)
            pinned.add(operand)
        left, right = locations[recipe.left], locations[recipe.right]
        if free:
            destination = heapq.heappop(free)
        else:
            evictable = set(locations) - protected - initial
            if not evictable:
                raise InvalidGraph("no register available for recomputation")
            victim = max(evictable, key=eviction_priority)
            destination = locations.pop(victim)
        if len(program) >= instruction_limit:
            raise InvalidGraph("recomputation exceeds improvement budget")
        program.append([recipe.operator, left, right, destination])
        locations[value] = destination
        peak = max(peak, len(locations))

    try:
        for position, value in enumerate(graph):
            ensure(value, set())
    except RecursionError as error:
        raise InvalidGraph("recomputation dependency chain too deep") from error
    validate_program(puzzle, program)
    return program, peak


def schedule(puzzle, graph, instruction_limit=None):
    """Try dependency-first and pressure-first orders, then reverse target order."""
    initial = set(puzzle.starting_values)
    for targets in (puzzle.targets, tuple(reversed(puzzle.targets))):
        ordered = close_graph(targets, initial, graph, {})
        for mode in ("dependency", "pressure"):
            try:
                return emit_graph(puzzle, ordered, mode)
            except InvalidGraph:
                continue
    if instruction_limit is not None:
        for targets in (puzzle.targets, tuple(reversed(puzzle.targets))):
            ordered = close_graph(targets, initial, graph, {})
            try:
                return emit_with_recomputation(puzzle, ordered, instruction_limit)
            except InvalidGraph:
                continue
    raise InvalidGraph("all scheduling orders exceed register limit")


def proposals(graph, catalog, costs, initial, limit):
    """Include coordinated moves sharing one operand, beyond single-node edits."""
    available = set(graph) | initial
    singles = []
    groups = defaultdict(dict)
    for value in sorted(graph):
        for recipe in sorted(catalog[value]):
            if recipe == graph[value]:
                continue
            new = [v for v in recipe.operands if v not in available]
            estimate = sum(costs[v] for v in new)
            singles.append((estimate, value, recipe))
            for operand in recipe.operands:
                previous = groups[operand].get(value)
                if previous is None or (estimate, recipe) < previous:
                    groups[operand][value] = (estimate, recipe)
    singles.sort()
    for _, value, recipe in singles[:limit]:
        yield {value: recipe}
    ranked_groups = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    for _, group in ranked_groups[:32]:
        if len(group) >= 2:
            ranked = sorted(group, key=lambda v: (group[v][0], v))[:6]
            yield {value: group[value][1] for value in ranked}


def rewrite_available_values(puzzle, program, catalog, rounds=3):
    """Rewrite SSA nodes using operands physically available at that point.

    Distinct occurrences stay distinct, avoiding the long lifetimes introduced
    by global value merging. Exact numeric relations also supply new recipes.
    Each trial is scored by the live multi-output dependency cone, including
    transient targets. Source occurrences always precede the rewritten node.
    """
    nodes, values, initial, initial_targets, occurrences, _ = build_ssa(puzzle, program)
    register_nodes = [-1 - i for i in range(len(puzzle.starting_values))]
    register_nodes += [None] * (puzzle.registers - len(register_nodes))
    alternatives = {}
    for index, (op, a, b, destination) in enumerate(program):
        left, right = register_nodes[a], register_nodes[b]
        result = execute(op, values[left], values[right])
        if index not in nodes:
            register_nodes[destination] = left if result == values[left] else right
            continue
        available = {}
        for node in register_nodes:
            if node is not None:
                available.setdefault(values[node], node)
        recipes = set(catalog.get(result, ()))
        for operand in available:
            # Generate only exact legal identities for this concrete result.
            if result - operand in available:
                recipes.add(Recipe("+", operand, result - operand))
            if operand - result in available:
                recipes.add(Recipe("-", operand, operand - result))
            if result % operand == 0 and result // operand in available:
                recipes.add(Recipe("*", operand, result // operand))
            if operand * result in available:
                recipes.add(Recipe("/", operand * result, operand))
        choices = set()
        for recipe in recipes:
            if recipe.left in available and recipe.right in available:
                candidate = Node(recipe.operator, available[recipe.left], available[recipe.right], result, index)
                if candidate != nodes[index]:
                    choices.add(candidate)
        alternatives[index] = sorted(choices, key=lambda n: (n.left, n.right, n.operator))
        register_nodes[destination] = index

    def required():
        return select_required_nodes(puzzle, nodes, initial, initial_targets, occurrences)

    live = required()
    moves = 0
    evaluated = 0
    for _ in range(rounds):
        previous_moves = moves
        # Work from consumers towards producers so new dead dependency cones
        # can be removed in the same pass.
        for index in sorted(live, reverse=True):
            if index not in live:
                continue
            original = nodes[index]
            winner, winner_live = original, live
            for candidate in alternatives.get(index, ()):
                if candidate == original:
                    continue
                nodes[index] = candidate
                trial_live = required()
                evaluated += 1
                if len(trial_live) < len(winner_live):
                    winner, winner_live = candidate, trial_live
            nodes[index] = winner
            if winner != original:
                live = winner_live
                moves += 1
        if moves == previous_moves:
            break
    candidate = emit_ssa(puzzle, nodes, values, live)
    validate_program(puzzle, candidate)
    return candidate, {"ssa_rewrites": moves, "ssa_candidates": evaluated}


def select_executable_graph(puzzle, graphs, instruction_limit, deadline=None):
    """Select by emitted length, allowing a larger DAG to beat a failed one."""
    selected = None
    failures = 0
    for graph in graphs:
        if deadline is not None and time.process_time() >= deadline:
            break
        if len(graph) > instruction_limit:
            continue
        try:
            program, peak = schedule(puzzle, graph, instruction_limit)
        except InvalidGraph:
            failures += 1
            continue
        selected = graph, program, peak
        instruction_limit = len(program) - 1
    return selected, failures


def optimize(puzzle, incumbent, donors, rounds=12, proposal_limit=192, candidate_width=1,
             deadline=None):
    initial = set(puzzle.starting_values)
    catalog = defaultdict(set)
    seeds = []
    for program in [incumbent, *donors]:
        recipes, seed = extract_recipes(puzzle, program)
        for value, alternatives in recipes.items():
            catalog[value].update(alternatives)
        seeds.append(seed)
    ssa_candidate, ssa_metadata = rewrite_available_values(puzzle, incumbent, catalog)
    if len(ssa_candidate) < len(incumbent):
        recipes, seed = extract_recipes(puzzle, ssa_candidate)
        for value, alternatives in recipes.items():
            catalog[value].update(alternatives)
        seeds.insert(0, seed)
    fallback, costs = cheapest_recipes(initial, catalog)
    metadata = {"catalog_values": len(catalog), "catalog_recipes": sum(map(len, catalog.values())),
                "evaluated_graphs": 0, "cyclic_candidates": 0, "schedule_failures": 0,
                "accepted_moves": 0, "peak_registers": None, "recomputed_instructions": 0,
                "executable_alternative_wins": 0,
                "graph_budget_exhausted": False,
                "ssa_improvement": len(incumbent) - len(ssa_candidate), **ssa_metadata}
    best = ssa_candidate if len(ssa_candidate) < len(incumbent) else incumbent
    candidate_seeds = []
    seen_seeds = set()
    for seed in [*seeds, fallback]:
        graph = close_graph(puzzle.targets, initial, seed, fallback)
        signature = frozenset(graph.items())
        if signature not in seen_seeds:
            seen_seeds.add(signature)
            candidate_seeds.append(graph)
    # Preserve the current graph as a search seed even if another source has a
    # smaller but unschedulable DAG. Try at most three distinct starting graphs.
    ordered_seeds = [candidate_seeds[0]]
    ordered_seeds += sorted(candidate_seeds[1:], key=len)[:2]

    def consider(graph):
        nonlocal best
        if deadline is not None and time.process_time() >= deadline:
            metadata["graph_budget_exhausted"] = True
            return
        if len(graph) >= len(best):
            return
        try:
            program, peak = schedule(puzzle, graph, len(best) - 1)
        except InvalidGraph:
            metadata["schedule_failures"] += 1
            return
        best = program
        metadata["peak_registers"] = peak
        metadata["recomputed_instructions"] = len(program) - len(graph)

    for graph in candidate_seeds:
        consider(graph)
    for graph in ordered_seeds:
        for _ in range(rounds):
            if deadline is not None and time.process_time() >= deadline:
                metadata["graph_budget_exhausted"] = True
                break
            finalists = []
            for patch in proposals(graph, catalog, costs, initial, proposal_limit):
                if deadline is not None and time.process_time() >= deadline:
                    metadata["graph_budget_exhausted"] = True
                    break
                selected = graph | patch
                metadata["evaluated_graphs"] += 1
                try:
                    candidate = close_graph(puzzle.targets, initial, selected, fallback)
                except InvalidGraph:
                    metadata["cyclic_candidates"] += 1
                    continue
                if len(candidate) >= len(graph):
                    continue
                if len(finalists) >= candidate_width and len(candidate) >= len(finalists[-1]):
                    continue
                if any(candidate == previous for previous in finalists):
                    continue
                finalists.append(candidate)
                finalists.sort(key=len)
                del finalists[candidate_width:]
            if not finalists:
                break
            metadata["accepted_moves"] += 1
            selected, failures = select_executable_graph(puzzle, finalists, len(best) - 1, deadline)
            metadata["schedule_failures"] += failures
            if selected is None:
                graph = finalists[0]
            else:
                graph, best, peak = selected
                metadata["executable_alternative_wins"] += graph != finalists[0]
                metadata["peak_registers"] = peak
                metadata["recomputed_instructions"] = len(best) - len(graph)
    final_ssa, final_metadata = rewrite_available_values(puzzle, best, catalog)
    if len(final_ssa) < len(best):
        metadata["final_ssa_improvement"] = len(best) - len(final_ssa)
        metadata["ssa_rewrites"] += final_metadata["ssa_rewrites"]
        best = final_ssa
        # The final SSA allocation has a different lifetime layout.
        metadata["peak_registers"] = None
    validate_program(puzzle, best)
    return best, metadata


def solve_job(job):
    puzzle, incumbent, donors, rounds, proposal_limit, candidate_width = job
    started = time.monotonic()
    program, metadata = optimize(puzzle, incumbent, donors, rounds, proposal_limit, candidate_width)
    return puzzle.puzzle_id, program, round(time.monotonic() - started, 4), metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--proposal-limit", type=int, default=192)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--candidate-width", type=int, default=1)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int)
    args = parser.parse_args()
    puzzles = load_puzzles(args.puzzles)
    end = len(puzzles) if args.end_index is None else args.end_index
    if not 0 <= args.start_index <= end <= len(puzzles):
        parser.error("invalid puzzle range")
    if args.rounds < 0 or min(args.proposal_limit, args.workers, args.candidate_width) < 1:
        parser.error("rounds must be nonnegative; search widths and workers positive")
    # Validate all source files independently before extracting any recipes.
    for path in [args.current, *args.source]:
        validate(args.puzzles, path)
    order, current = read_submission(args.current)
    sources = [read_submission(path)[1] for path in args.source]
    selected = dict(current)
    rows = []
    started = time.monotonic()
    jobs = ((puzzle, current[puzzle.puzzle_id], [source[puzzle.puzzle_id] for source in sources],
             args.rounds, args.proposal_limit, args.candidate_width) for puzzle in puzzles[args.start_index:end])
    executor = ProcessPoolExecutor(max_workers=args.workers) if args.workers > 1 else None
    results = executor.map(solve_job, jobs) if executor is not None else map(solve_job, jobs)
    try:
        for puzzle_id, program, seconds, metadata in results:
            selected[puzzle_id] = program
            rows.append({"id": puzzle_id, "current_instructions": len(current[puzzle_id]),
                         "selected_instructions": len(program),
                         "improvement": len(current[puzzle_id]) - len(program),
                         "seconds": seconds, **metadata})
            if len(rows) % 10 == 0 or len(rows) == end - args.start_index:
                print(json.dumps({"processed": len(rows), "improvement": sum(r["improvement"] for r in rows),
                                  "elapsed_seconds": round(time.monotonic() - started, 1)}), flush=True)
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_submission(args.output, order, selected)
    validation = validate(args.puzzles, args.output)
    report = {"optimizer": "shared_recipe_catalog_local_graph_search", "current_submission": str(args.current),
              "sources": list(map(str, args.source)), "output_submission": str(args.output),
              "start_index": args.start_index, "end_index": end, "rounds": args.rounds,
              "proposal_limit": args.proposal_limit, "workers": args.workers,
              "candidate_width": args.candidate_width,
              "current_score": sum(map(len, current.values())), "selected_score": validation["score"],
              "total_improvement": sum(r["improvement"] for r in rows),
              "improved_puzzles": sum(r["improvement"] > 0 for r in rows),
              "elapsed_seconds": round(time.monotonic() - started, 3), "validation": validation,
              "largest_improvements": sorted(rows, key=lambda r: (-r["improvement"], r["id"]))[:30],
              "puzzles": rows}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("puzzles", "largest_improvements")}, indent=2))


if __name__ == "__main__":
    main()
