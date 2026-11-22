"""Beam search over joint backward reductions; all solutions are replayed."""
from __future__ import annotations

import time
from recipe_graph_optimizer import Recipe, InvalidGraph, close_graph
from register_scheduler import schedule_with_search
from short_synthesis_optimizer import one_step_recipes
from tiny_solver import validate_program


def moves(puzzle, remaining, graph, weight, one, branch_limit=6):
    initial = set(puzzle.starting_values)
    value = max(remaining)
    rest = remaining - {value}
    patches = []
    if value == 1:
        patches.append({1: Recipe('/', puzzle.starting_values[0], puzzle.starting_values[0])})
    elif value in one:
        op, a, b, _ = one[value]
        patches.append({value: Recipe(op, a, b)})
    else:
        anchors = sorted((rest | initial | {1,2,4,8,16,32,64,128,256}) - {value})
        for a in anchors:
            if a > puzzle.value_limit or a >= 2*value or (a > value and a not in initial):
                continue
            delta = abs(value-a)
            if 0 < delta < value:
                patches.append({value: Recipe('+' if value>a else '-', a, delta)})
            if not 1 < a < value:
                continue
            q, r = divmod(value, a)
            for quotient, remainder, op in ((q,r,'+'),(q+1,a-r,'-')):
                product = quotient*a
                if not remainder:
                    patches.append({value: Recipe('*',a,quotient)})
                elif product <= puzzle.value_limit and product not in graph and quotient < value:
                    if quotient == 1:
                        patches.append({value: Recipe(op,a,remainder)})
                    else:
                        patches.append({product: Recipe('*',a,quotient),
                                        value: Recipe(op,product,remainder)})
    candidates = {}
    existing = initial | graph.keys()
    for patch in patches:
        needed = (rest | {a for r in patch.values() for a in r.operands}) - existing - patch.keys()
        key = frozenset(needed)
        new_count = len(graph) + len(patch.keys()-existing)
        score = new_count + weight*sum(v.bit_length() for v in needed)
        ranking = (score, new_count, len(needed), max(needed,default=0))
        previous = candidates.get(key)
        if previous is None or ranking < previous[0]:
            candidates[key] = (ranking, needed, patch)
    return sorted(candidates.values(),key=lambda c:c[0])[:branch_limit]


def beam_graphs(puzzle, instruction_limit, width=16, branch_limit=6, weight=.25, deadline=None):
    initial = set(puzzle.starting_values)
    one = one_step_recipes(initial,puzzle.value_limit)
    remaining = set(puzzle.targets)-initial
    if not remaining:
        return [{}], {'beam_expanded':0,'beam_budget_exhausted':False}
    beam = [(remaining,{})]
    finals = []
    expanded = 0
    exhausted = False
    for _ in range(instruction_limit):
        if deadline is not None and time.process_time() >= deadline:
            exhausted = True
            break
        next_states = {}
        for needed, graph in beam:
            for ranking, new_needed, patch in moves(puzzle,needed,graph,weight,one,branch_limit):
                expanded += 1
                candidate = graph | patch
                if len(candidate) >= instruction_limit:
                    continue
                if not new_needed:
                    finals.append(candidate)
                    continue
                signature = frozenset(new_needed)
                previous = next_states.get(signature)
                if previous is None or ranking < previous[0]:
                    next_states[signature] = (ranking,new_needed,candidate)
        finals.sort(key=len)
        del finals[16:]
        if not next_states:
            beam=[]
            break
        selected=sorted(next_states.values(),key=lambda c:c[0])[:width]
        beam=[(needed,graph) for _,needed,graph in selected]
    # Complete a few surviving paths if the cooperative time limit interrupts.
    for needed, graph in beam[:3]:
        while needed and len(graph)<instruction_limit:
            options=moves(puzzle,needed,graph,weight,one,1)
            if not options:break
            _,needed,patch=options[0]
            graph=graph|patch
        if not needed and len(graph)<instruction_limit:
            finals.append(graph)
    finals.sort(key=len)
    return finals[:16],{'beam_expanded':expanded,'beam_budget_exhausted':exhausted}


def optimize_beam(puzzle, incumbent, budget=6, width=16, weights=(.15,.25,.4)):
    best=incumbent
    start=time.process_time()
    expanded=0
    failures=0
    for index,weight in enumerate(weights):
        deadline=start+budget*(index+1)/len(weights)
        graphs,info=beam_graphs(puzzle,len(best),width=width,weight=weight,deadline=deadline)
        expanded+=info['beam_expanded']
        for graph in graphs:
            if len(graph)>=len(best):continue
            try:
                graph=close_graph(puzzle.targets,set(puzzle.starting_values),graph,{})
                candidate,_=schedule_with_search(puzzle,graph,len(best)-1,attempts=12)
            except InvalidGraph:
                failures+=1;continue
            validate_program(puzzle,candidate)
            if len(candidate)<len(best):best=candidate
    return best,{'beam_expanded':expanded,'beam_failures':failures,
                 'cpu_seconds':time.process_time()-start}
