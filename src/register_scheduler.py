"""Bounded search over target and operand orders before recomputing values."""
from collections import Counter
import random
from recipe_graph_optimizer import InvalidGraph, close_graph, emit_graph, schedule


def ordered_graph(targets, initial, graph, operand_key):
    ordered = {}
    for target in targets:
        stack = [(target, False)]
        while stack:
            value, exiting = stack.pop()
            if value in initial or value in ordered:
                continue
            recipe = graph[value]
            if exiting:
                ordered[value] = recipe
                continue
            stack.append((value, True))
            operands = sorted(recipe.operands, key=operand_key, reverse=True)
            stack.extend((a, False) for a in operands)
    return ordered


def register_peak(puzzle, graph):
    uses = Counter(a for r in graph.values() for a in r.operands)
    live = sum(uses[v] > 0 for v in set(puzzle.starting_values))
    peak = live
    for value, recipe in graph.items():
        dying = sum(uses[a] == 1 for a in recipe.operands)
        peak = max(peak, live + (not dying))
        for a in recipe.operands:
            uses[a] -= 1
        live += (uses[value] > 0) - dying
    return peak


def schedule_with_search(puzzle, graph, instruction_limit=None, attempts=80):
    try:
        return schedule(puzzle, graph)
    except InvalidGraph:
        pass
    initial = set(puzzle.starting_values)
    graph = close_graph(puzzle.targets, initial, graph, {})
    masks = {v: 0 for v in initial}
    heights = {v: 0 for v in initial}
    needs = {v: 1 for v in initial}
    for i, (v, r) in enumerate(graph.items()):
        masks[v] = (1 << i) | masks[r.left] | masks[r.right]
        heights[v] = 1 + max(heights[a] for a in r.operands)
        ns = sorted((needs[a] for a in r.operands), reverse=True)
        needs[v] = max(n + i for i, n in enumerate(ns))
    keys = [lambda v: v, lambda v: (-needs[v], -masks[v].bit_count(), v),
            lambda v: (-heights[v], v)]
    targets = list(puzzle.targets)
    orders = [targets, targets[::-1], sorted(targets, key=lambda v: masks[v].bit_count()),
              sorted(targets, key=lambda v: -masks[v].bit_count()),
              sorted(targets, key=lambda v: needs[v]), sorted(targets, key=lambda v: -needs[v])]
    # Greedily cover the closest remaining output in dependency-set distance.
    for reverse in (False, True):
        remaining = set(targets)
        covered = 0
        order = []
        while remaining:
            value = min(remaining, key=lambda v: ((-1 if reverse else 1) *
                        (masks[v] & ~covered).bit_count(), v))
            order.append(value)
            covered |= masks[value]
            remaining.remove(value)
        orders.append(order)
    rng = random.Random(130000)
    while len(orders) * len(keys) < attempts:
        order = targets[:]
        rng.shuffle(order)
        orders.append(order)
    count = 0
    finalists = []
    for order in orders:
        for key in keys:
            if count >= attempts:
                break
            count += 1
            candidate = ordered_graph(order, initial, graph, key)
            peak = register_peak(puzzle, candidate)
            if peak <= puzzle.registers:
                return emit_graph(puzzle, candidate, 'dependency')
            finalists.append((peak, count, candidate))
            finalists.sort(key=lambda item: item[:2])
            del finalists[6:]
    if instruction_limit is not None:
        for _, _, candidate in finalists:
            try:
                return emit_cached(puzzle, candidate, instruction_limit)
            except InvalidGraph:
                continue
    return schedule(puzzle, graph, instruction_limit)


def emit_cached(puzzle, graph, instruction_limit):
    """Rematerialize evicted values; discard dead results before useful ones."""
    from bisect import bisect_right
    from collections import defaultdict
    from tiny_solver import validate_program
    initial = set(puzzle.starting_values)
    next_uses = defaultdict(list)
    costs = {v: 0 for v in initial}
    for i, (v, r) in enumerate(graph.items()):
        costs[v] = 1 + sum(costs[a] for a in r.operands)
        for a in r.operands:
            next_uses[a].append(i)
    locations = {}
    for i, v in enumerate(puzzle.starting_values):
        if next_uses[v]:
            locations.setdefault(v, i)
    free = sorted(set(range(puzzle.registers)) - set(locations.values()), reverse=True)
    program = []
    produced = set(initial)
    position = 0
    peak = len(locations)

    def priority(v):
        uses = next_uses[v]
        index = bisect_right(uses, position)
        dead = index == len(uses)
        next_pos = len(graph) + 1 if dead else uses[index]
        return dead, (next_pos-position)/max(1, costs[v]), next_pos, -v

    def ensure(value, protected):
        nonlocal peak
        if value in locations:
            return
        if value in initial:
            raise InvalidGraph('lost initial value')
        recipe = graph[value]
        pinned = set(protected)
        for a in sorted(recipe.operands, key=lambda a: (-costs[a], a)):
            ensure(a, pinned)
            pinned.add(a)
        left, right = locations[recipe.left], locations[recipe.right]
        if free:
            destination = free.pop()
        else:
            eligible = set(locations) - protected - initial
            if not eligible:
                raise InvalidGraph('no cache register')
            victim = max(eligible, key=priority)
            destination = locations.pop(victim)
        if len(program) >= instruction_limit:
            raise InvalidGraph('cache instruction budget')
        program.append([recipe.operator, left, right, destination])
        locations[value] = destination
        produced.add(value)
        peak = max(peak, len(locations))

    try:
        for position, value in enumerate(graph):
            if value not in produced:
                ensure(value, set())
            # Values with no remaining direct consumer can be recovered later
            # from pinned inputs if an evicted descendant must be regenerated.
            for v in list(locations):
                if v not in initial and bisect_right(next_uses[v], position) == len(next_uses[v]):
                    free.append(locations.pop(v))
    except RecursionError as error:
        raise InvalidGraph('cache dependency chain too deep') from error
    validate_program(puzzle, program)
    return program, peak
