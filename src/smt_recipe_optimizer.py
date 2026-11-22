"""Optional native Z3 selection of whole acyclic recipe DAGs."""
from collections import defaultdict
from pathlib import Path
import subprocess
import time
from recipe_graph_optimizer import Recipe, InvalidGraph, extract_recipes, close_graph, cheapest_recipes
from global_synthesis_optimizer import global_proposals
from joint_reduction_solver import build_graph
from register_scheduler import schedule_with_search
from tiny_solver import validate_program


def recipe_catalog(puzzle, incumbent, donors=(), enrich=False, construct=True):
    initial=set(puzzle.starting_values)
    catalog=defaultdict(set)
    for program in (incumbent,*donors):
        recipes,_=extract_recipes(puzzle,program)
        for v,rs in recipes.items():catalog[v].update(rs)
    _,seed=extract_recipes(puzzle,incumbent)
    graph=close_graph(puzzle.targets,initial,seed,{})
    proposals,_=global_proposals(puzzle,graph,limit=128,deadline=time.process_time()+.4)
    for patch in proposals:
        for v,r in patch.items():catalog[v].add(r)
    for weight in ((.15,.25,.4) if construct else ()):
        try:
            candidate=build_graph(puzzle,weight,0,factor_mode=1)
        except InvalidGraph:
            continue
        for v,r in candidate.items():catalog[v].add(r)
    if enrich:
        # Include cost-neutral alternatives too: several can pay off together.
        values=sorted(initial | set(catalog))
        known=set(values)
        for i,a in enumerate(values):
            for b in values[:i+1]:
                possibilities=[(a+b,'+',a,b),(a*b,'*',a,b)]
                if a>b:possibilities.append((a-b,'-',a,b))
                if a%b==0:possibilities.append((a//b,'/',a,b))
                for v,op,left,right in possibilities:
                    if v in known and v not in initial and v not in (left,right):
                        catalog[v].add(Recipe(op,left,right))
    return initial,catalog,graph


def optimize_smt(puzzle, incumbent, donors=(), timeout_ms=2000, binary=Path('build/select_recipes'),
                 enrich=False, construct=True):
    initial,catalog,graph=recipe_catalog(puzzle,incumbent,donors,enrich,construct)
    fallback,costs=cheapest_recipes(initial,catalog)
    values=sorted(set(fallback)-initial)
    indices={v:i for i,v in enumerate(values)}
    recipes=[(v,r) for v in values for r in sorted(catalog[v])
             if all(a in initial or a in indices for a in r.operands)]
    targets=[indices[v] for v in puzzle.targets if v not in initial]
    if not targets:return incumbent,{'smt_status':'initial','smt_saved':0}
    lines=[f'{len(values)} {len(recipes)} {len(targets)} {len(incumbent)-1} {timeout_ms}',
           ' '.join(map(str,targets))]
    lines.extend(f'{indices[v]} {indices.get(r.left,-1)} {indices.get(r.right,-1)}' for v,r in recipes)
    try:
        completed=subprocess.run([str(binary.resolve())],input='\n'.join(lines)+'\n',text=True,
                                  capture_output=True,timeout=timeout_ms/1000+10)
    except subprocess.TimeoutExpired:
        return incumbent,{'smt_status':'process_timeout','smt_saved':0}
    output=completed.stdout.splitlines()
    info={'smt_values':len(values),'smt_recipes':len(recipes),
          'smt_status':output[0] if output else 'no_output','smt_saved':0,
          'smt_diagnostics':completed.stderr.strip()[:400]}
    if not output or output[0] in ('unsat','no_model') or len(output)<2:
        return incumbent,info
    chosen=[int(i) for i in output[1].split()]
    selected={recipes[i][0]:recipes[i][1] for i in chosen}
    try:
        trial=close_graph(puzzle.targets,initial,selected,{})
        candidate,_=schedule_with_search(puzzle,trial,len(incumbent)-1,attempts=18)
    except InvalidGraph:
        info['smt_schedule_failed']=True
        return incumbent,info
    validate_program(puzzle,candidate)
    if len(candidate)<len(incumbent):
        info['smt_saved']=len(incumbent)-len(candidate)
        return candidate,info
    return incumbent,info
