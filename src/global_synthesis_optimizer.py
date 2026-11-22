"""Synthesize shared intermediates across a numeric DAG, then schedule exactly.

Unlike private SSA-window synthesis, proposals may rewrite several consumers
at once and reuse values that were not simultaneously present in the old
register file. A valid emitted program and a strict length decrease are required.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import time
from recipe_graph_optimizer import Recipe, InvalidGraph, close_graph, extract_recipes, schedule
from short_synthesis_optimizer import inverse_partners
from tiny_solver import validate_program
from register_scheduler import schedule_with_search


def global_proposals(puzzle, graph, limit=256, deadline=None, cross_branch=False):
    initial = set(puzzle.starting_values)
    values = sorted(initial) + list(graph)
    rank = {v: i for i, v in enumerate(values)}
    masks = {v: 0 for v in initial}
    for i, (v, recipe) in enumerate(graph.items()):
        masks[v] = (1 << i) | masks[recipe.left] | masks[recipe.right]
    uses = Counter(a for r in graph.values() for a in r.operands)
    protected = set(puzzle.targets)
    cones = {}
    for root in graph:
        cone = {root}
        removed_uses = Counter()
        stack = [root]
        while stack:
            for a in graph[stack.pop()].operands:
                removed_uses[a] += 1
                if a in graph and a not in protected and a not in cone and removed_uses[a] == uses[a]:
                    cone.add(a)
                    stack.append(a)
        cones[root] = sum(1 << (rank[v] - len(initial)) for v in cone if v != root)
    pairs = {}
    direct = {}
    direct_scores = {}
    future_direct = {}
    future_scores = {}
    root_bits = {v: 1 << i for i, v in enumerate(graph)}
    for i, a in enumerate(values):
        if deadline is not None and time.process_time() >= deadline:
            return [], {'global_pair_values': len(pairs), 'global_budget_exhausted': True}
        for b in values[:i + 1]:
            candidates = [(a + b, '+', a, b), (a * b, '*', a, b)]
            if a != b:
                candidates.append((abs(a - b), '-', max(a,b), min(a,b)))
            if a % b == 0:
                candidates.append((a // b, '/', a, b))
            elif b % a == 0:
                candidates.append((b // a, '/', b, a))
            for result, op, left, right in candidates:
                if not 0 < result <= puzzle.value_limit or result in initial:
                    continue
                recipe = Recipe(op, left, right)
                support = masks[a] | masks[b]
                if result in graph:
                    if i >= rank[result]:
                        if cross_branch and not support & root_bits[result]:
                            saving = (cones[result] & ~support).bit_count()
                            if saving > future_scores.get(result, 0):
                                future_direct[result] = recipe
                                future_scores[result] = saving
                        continue
                    deleted = (masks[result] & ~root_bits[result]) if cross_branch else cones[result]
                    saving = (deleted & ~support).bit_count()
                    if saving > direct_scores.get(result, 0):
                        direct[result] = recipe
                        direct_scores[result] = saving
                elif result not in pairs or (cross_branch and support.bit_count() < pairs[result][2].bit_count()):
                    pairs[result] = (recipe, i, support)
    grouped = defaultdict(dict)
    scores = defaultdict(int)
    for root in graph:
        if not cross_branch and not cones[root]:
            continue
        if deadline is not None and time.process_time() >= deadline:
            break
        for b in values[:rank[root]]:
            for missing, op, left, right in inverse_partners(root, b, puzzle.value_limit):
                if missing not in pairs:
                    continue
                recipe, source_rank, support = pairs[missing]
                forbidden = bool(support & root_bits[root]) if cross_branch else source_rank >= rank[root]
                if forbidden:
                    continue
                deleted = (masks[root] & ~root_bits[root]) if cross_branch else cones[root]
                saving = (deleted & ~(support | masks[b])).bit_count()
                if not saving:
                    continue
                prior = grouped[missing].get(root)
                if prior is None or saving > prior[0]:
                    grouped[missing][root] = (saving, Recipe(op, left, right))
                    scores[missing] += saving - (prior[0] if prior else 0)
    proposals = []
    if direct:
        proposals.append(direct)
    if future_direct:
        proposals.append(future_direct)
        proposals.extend({v: recipe} for v, recipe in future_direct.items())
    for missing in sorted(scores, key=lambda v: (-scores[v], v))[:limit]:
        if scores[missing] <= 1:
            continue
        patch = {missing: pairs[missing][0]}
        patch.update({v: r for v, (_, r) in grouped[missing].items()})
        proposals.append(patch)
    return proposals, {'global_pair_values': len(pairs), 'global_groups': len(grouped),
                       'global_direct_rewrites': len(direct), 'global_future_rewrites': len(future_direct),
                       'global_budget_exhausted': deadline is not None and time.process_time() >= deadline}


def optimize_global(puzzle, incumbent, rounds=4, proposal_limit=256, deadline=None, cross_branch=False):
    best = incumbent
    metadata = {'global_rounds': 0, 'global_graphs': 0, 'global_failures': 0,
                'global_rewrites': 0, 'global_pair_values': 0}
    _, seed = extract_recipes(puzzle, incumbent)
    graph = close_graph(puzzle.targets, set(puzzle.starting_values), seed, {})
    for _ in range(rounds):
        if deadline is not None and time.process_time() >= deadline:
            break
        proposals, info = global_proposals(puzzle, graph, proposal_limit, deadline, cross_branch)
        metadata.update(info)
        metadata['global_rounds'] += 1
        finalists = []
        for patch in proposals:
            try:
                trial = close_graph(puzzle.targets, set(puzzle.starting_values), graph | patch, {})
            except InvalidGraph:
                continue
            metadata['global_graphs'] += 1
            if len(trial) < len(graph):
                finalists.append(trial)
        if not finalists:
            break
        finalists.sort(key=len)
        chosen = None
        for trial in finalists[:16]:
            if len(trial) >= len(best):
                continue
            try:
                candidate, _ = schedule_with_search(puzzle, trial, len(best) - 1, attempts=12)
            except InvalidGraph:
                metadata['global_failures'] += 1
                continue
            if len(candidate) < len(best):
                best = candidate
                chosen = trial
        if chosen is None:
            break
        graph = chosen
        metadata['global_rewrites'] += 1
    validate_program(puzzle, best)
    metadata['global_saved'] = len(incumbent) - len(best)
    return best, metadata


def solve_job(job):
    puzzle, incumbent, rounds, proposal_limit, budget, cross_branch = job
    started = time.process_time()
    candidate, info = optimize_global(puzzle, incumbent, rounds, proposal_limit, started + budget, cross_branch)
    return puzzle.puzzle_id, candidate, {'id': puzzle.puzzle_id,
            'before': len(incumbent), 'after': len(candidate),
            'saved': len(incumbent) - len(candidate),
            'cpu_seconds': round(time.process_time() - started, 6), **info}


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
    parser.add_argument('--rounds', type=int, default=8)
    parser.add_argument('--proposal-limit', type=int, default=256)
    parser.add_argument('--cpu-budget', type=float, default=12)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--cross-branch', action='store_true')
    parser.add_argument('--start-index', type=int, default=0)
    parser.add_argument('--end-index', type=int)
    args = parser.parse_args()
    puzzles = load_puzzles(args.puzzles)
    end = len(puzzles) if args.end_index is None else args.end_index
    if not 0 <= args.start_index <= end <= len(puzzles):
        parser.error('invalid puzzle range')
    if min(args.rounds, args.proposal_limit, args.cpu_budget, args.workers) <= 0:
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
        report = {'optimizer': 'global_shared_intermediate_synthesis',
                  'input': str(args.current), 'output': str(args.output),
                  'current_score': base_validation['score'],
                  'selected_score': sum(map(len, selected.values())),
                  'saved': sum(r['saved'] for r in rows),
                  'improved': sum(r['saved'] > 0 for r in rows),
                  'processed': len(rows), 'start_index': args.start_index, 'end_index': end,
                  'rounds': args.rounds, 'proposal_limit': args.proposal_limit,
                  'cpu_budget': args.cpu_budget, 'workers': args.workers,
                  'cross_branch': args.cross_branch,
                  'complete': complete, 'wall_seconds': round(time.monotonic() - started, 3),
                  'puzzles': rows}
        if complete:
            report['validation'] = validate(args.puzzles, args.output)
        temporary = args.report.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(args.report)
        return report
    jobs = ((p, selected[p.puzzle_id], args.rounds, args.proposal_limit, args.cpu_budget, args.cross_branch)
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
