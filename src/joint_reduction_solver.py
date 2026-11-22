"""Joint backward reduction by differences, exact quotients and remainders.

The working set contains values still required by any output. A dependency
already in that set has zero marginal construction estimate. Each reduction
replaces the largest outstanding value, paying for new operands and operations.
The estimate ranks alternatives only: final selection uses emitted instruction
counts and independent arithmetic replay. No constants are introduced for free.
"""
from functools import lru_cache
from math import gcd
import time
from recipe_graph_optimizer import Recipe, close_graph, schedule, InvalidGraph
from short_synthesis_optimizer import one_step_recipes
from signed_digit_solver import choose_digits
from register_scheduler import schedule_with_search
from tiny_solver import validate_program
from small_factor_synthesis import construction_estimate, factor_patches

def build_graph(p, weight, metric, extended=False, factor_mode=0, pair_mode=False, smooth_mode=False,
                rng=None, temperature=0.0, order_window=1, reuse_graph=False):
    initial = set(p.starting_values)
    needed = set(p.targets) - initial
    graph = {}
    coverages = {}
    one = one_step_recipes(initial, p.value_limit)
    seed_bases = [1, 2, 4, 8, 16, 32, 64, 128, 256]
    if extended:
        seed_bases = sorted(set(seed_bases + list(one) +
                           [1 << k for k in range(12, p.value_limit.bit_length(), 4)]))

    @lru_cache(maxsize=None)
    def estimate(value):
        if extended and value in one:
            return min(1, value.bit_length() * weight)
        if metric == 0:
            baseline = value.bit_length() * weight
            return min(baseline, construction_estimate(value, initial, one, weight)) if smooth_mode else baseline
        return len(choose_digits(value, p.value_limit)) * weight

    def cost(value):
        if value in initial or value in needed or value in graph:
            return 0
        return estimate(value) / coverages.get(value, 1) ** (0.5 if factor_mode == 1 else 1.0)

    while needed:
        value = (rng.choice(sorted(needed, reverse=True)[:order_window])
                 if rng is not None and order_window > 1 else max(needed))
        needed.remove(value)
        if value in graph:
            continue
        if value == 1:
            graph[1] = Recipe('/', p.starting_values[0], p.starting_values[0])
            continue
        if value in one:
            op, a, b, _ = one[value]
            graph[value] = Recipe(op, a, b)
            continue
        anchors = sorted((needed | initial) - {1})
        coverages = {}
        if factor_mode:
            factors = {gcd(value, a) for a in anchors} - {1, value}
            anchors = sorted(set(anchors) | factors)
            coverages = {a: 1 + sum(t % a == 0 for t in needed) for a in factors}
        anchors = sorted(set(anchors + seed_bases +
                         ([v for v in graph if v < value] if extended or reuse_graph else [])) - {value})
        choices = []
        for a in anchors:
            # An undefined larger anchor could introduce value -> anchor -> value.
            if a >= 2 * value or a > p.value_limit or (a > value and a not in initial):
                continue
            delta = abs(value - a)
            if 0 < delta < value:
                patch = {value: Recipe('+' if value > a else '-', a, delta)}
                choices.append((1 + cost(a) + cost(delta), 1, delta, patch))
            if a >= value or a == 1:
                continue
            quotient, remainder = divmod(value, a)
            for q, r, op in ((quotient, remainder, '+'), (quotient + 1, a - remainder, '-')):
                if r == 0:
                    patch = {value: Recipe('*', a, q)}
                    choices.append((1 + cost(a) + cost(q), 1, 0, patch))
                    continue
                product = q * a
                if product > p.value_limit or product in graph or q >= value:
                    continue
                patch = {product: Recipe('*', a, q), value: Recipe(op, product, r)}
                if q == 1:
                    patch = {value: Recipe(op, a, r)}
                choices.append((len(patch) + cost(a) + (cost(q) if q != 1 else 0) + cost(r),
                                len(patch), r, patch))
        if smooth_mode:
            for patch in factor_patches(p, value, graph):
                leaves = {a for recipe in patch.values() for a in recipe.operands} - patch.keys()
                choices.append((len(patch) + sum(cost(a) for a in leaves), len(patch), 0, patch))
        if pair_mode:
            ready = sorted(needed | initial)
            for i, a in enumerate(ready):
                for b in ready[:i + 1]:
                    options = [(a + b, '+', a, b), (a * b, '*', a, b)]
                    if a != b:
                        options.append((abs(a - b), '-', max(a, b), min(a, b)))
                    for combined, op, left, right in options:
                        if not 0 < combined <= p.value_limit or combined >= 2 * value:
                            continue
                        if combined in graph and combined > value:
                            continue
                        remainder = abs(value - combined)
                        if remainder == 0:
                            choices.append((1, 1, 0, {value: Recipe(op, left, right)}))
                            continue
                        if remainder >= value:
                            continue
                        patch = {value: Recipe('+' if value > combined else '-', combined, remainder)}
                        if combined not in initial and combined not in needed and combined not in graph:
                            patch[combined] = Recipe(op, left, right)
                        choices.append((len(patch) + cost(remainder), len(patch), remainder, patch))
        if not choices:
            raise InvalidGraph('no decreasing reduction')
        if rng is not None and temperature > 0:
            _, _, _, patch = min(choices, key=lambda choice: (choice[0] + temperature*rng.random(), *choice[1:3]))
        else:
            _, _, _, patch = min(choices, key=lambda choice: choice[:3])
        for result, recipe in patch.items():
            if result not in initial:
                graph[result] = recipe
        for recipe in patch.values():
            needed.update(v for v in recipe.operands if v not in initial and v not in graph)
        if len(graph) > 4000:
            raise InvalidGraph('reduction exceeds graph-size limit')
    return close_graph(p.targets, initial, graph, {})


def configurations(mode):
    basic = [(w, m, 0, False) for m, weights in ((0, (.1, .2, .35, .6)), (1, (.5, 1, 2)))
             for w in weights]
    factors = [(w, 0, f, False) for f in (1, 2) for w in (.15, .25, .4, .65)]
    pairs = [(w, 0, f, True) for f in (0, 1) for w in (.15, .25, .4, .65)]
    return {'baseline': basic, 'factors': factors, 'pairs': pairs,
            'combined': basic + factors + pairs}[mode]


def solve_job(args):
    puzzle, best, extended_options, *options = args
    configs = options[0] if options else configurations('baseline')
    attempts = options[1] if len(options) > 1 else 80
    before = len(best)
    winner = None
    failures = 0
    minimum_nodes = 10**9
    started = time.process_time()
    for extended in extended_options:
        for weight, metric, factor_mode, pair_mode in configs:
            try:
                graph = build_graph(puzzle, weight, metric, extended, factor_mode, pair_mode)
                minimum_nodes = min(minimum_nodes, len(graph))
                if len(graph) >= len(best):
                    continue
                candidate, _ = schedule_with_search(puzzle, graph, len(best) - 1, attempts)
            except InvalidGraph:
                failures += 1
                continue
            validate_program(puzzle, candidate)
            if len(candidate) < len(best):
                best = candidate
                winner = (weight, metric, extended, factor_mode, pair_mode)
    return puzzle.puzzle_id, best, {'id': puzzle.puzzle_id, 'before': before, 'after': len(best),
            'saved': before - len(best), 'parameters': winner, 'failures': failures,
            'minnodes': minimum_nodes, 'cpu_seconds': round(time.process_time() - started, 6)}


def main():
    import argparse
    from concurrent.futures import ProcessPoolExecutor
    import json
    from pathlib import Path
    from tiny_solver import load_puzzles, read_submission, write_submission
    from validate_submission import validate

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--puzzles', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--extended', action='store_true')
    parser.add_argument('--search', choices=('baseline','factors','pairs','combined'), default='baseline')
    parser.add_argument('--schedule-attempts', type=int, default=18)
    parser.add_argument('--start-index', type=int, default=0)
    parser.add_argument('--end-index', type=int)
    args = parser.parse_args()
    puzzles = load_puzzles(args.puzzles)
    end = len(puzzles) if args.end_index is None else args.end_index
    if not 0 <= args.start_index <= end <= len(puzzles):
        parser.error('invalid puzzle range')
    if min(args.workers, args.schedule_attempts) <= 0:
        parser.error('budgets and worker count must be positive')
    if args.current.resolve() == args.output.resolve():
        parser.error('output must preserve the input checkpoint')
    base_validation = validate(args.puzzles, args.current)
    order, selected = read_submission(args.current)
    rows = []
    started = time.monotonic()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    def checkpoint(complete=False):
        temporary = args.output.with_suffix('.csv.tmp')
        write_submission(temporary, order, selected)
        temporary.replace(args.output)
        report = {'optimizer': 'joint_backward_reduction',
                  'input': str(args.current), 'output': str(args.output),
                  'current_score': base_validation['score'],
                  'selected_score': sum(map(len, selected.values())),
                  'saved': sum(r['saved'] for r in rows),
                  'improved': sum(r['saved'] > 0 for r in rows),
                  'processed': len(rows), 'start_index': args.start_index, 'end_index': end,
                  'workers': args.workers, 'extended': args.extended,
                  'search': args.search, 'schedule_attempts': args.schedule_attempts,
                  'complete': complete, 'wall_seconds': round(time.monotonic() - started, 3),
                  'puzzles': rows}
        if complete:
            report['validation'] = validate(args.puzzles, args.output)
        temporary = args.report.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(args.report)
        return report
    jobs = ((p, selected[p.puzzle_id], (False, True) if args.extended else (False,), configurations(args.search), args.schedule_attempts)
            for p in puzzles[args.start_index:end])
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for puzzle_id, candidate, info in pool.map(solve_job, jobs):
            selected[puzzle_id] = candidate
            rows.append(info)
            if len(rows) % 10 == 0:
                print(json.dumps({'processed': len(rows), 'saved': sum(r['saved'] for r in rows),
                                  'seconds': round(time.monotonic() - started, 2)}), flush=True)
            if len(rows) % 100 == 0:
                checkpoint()
    report = checkpoint(True)
    print(json.dumps({k: v for k, v in report.items() if k != 'puzzles'}, indent=2))


if __name__ == '__main__':
    main()
