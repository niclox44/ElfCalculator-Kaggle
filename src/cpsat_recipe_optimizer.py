"""Optional CP-SAT backend for the locally generated shared-recipe catalogue."""
from pathlib import Path
import sys
DEPENDENCIES=Path(__file__).resolve().parents[1]/'.deps/ortools'
if DEPENDENCIES.is_dir():sys.path.insert(0,str(DEPENDENCIES))
from ortools.sat.python import cp_model
from smt_recipe_optimizer import recipe_catalog
from recipe_graph_optimizer import InvalidGraph,close_graph,cheapest_recipes
from register_scheduler import schedule_with_search
from tiny_solver import validate_program


def optimize_cpsat(puzzle,incumbent,donors=(),seconds=5,extra_catalog=None,harvest_helpers=False):
    initial,catalog,graph=recipe_catalog(puzzle,incumbent,donors,enrich=True,construct=False)
    if extra_catalog:
        for v,recipes in extra_catalog.items():catalog[v].update(recipes)
    if harvest_helpers:
        from multi_helper_optimizer import optimize_multi_helper
        optimize_multi_helper(puzzle,incumbent,limit=128,seconds=2,
                              proposal_sink=catalog,slack=1)
    fallback,_=cheapest_recipes(initial,catalog)
    values=sorted(set(fallback)-initial)
    if not values:return incumbent,{'status':'initial','saved':0}
    model=cp_model.CpModel()
    selected={v:model.new_bool_var(f'v{v}') for v in values}
    levels={v:model.new_int_var(1,len(values),f'd{v}') for v in values}
    choices={}
    depths={v:0 for v in initial}
    for v,r in graph.items():depths[v]=1+max(depths[r.left],depths[r.right])
    recipe_count=0
    for v in values:
        alternatives=[]
        for r in sorted(catalog[v]):
            if v in r.operands or any(a not in initial and a not in selected for a in r.operands):continue
            enabled=model.new_bool_var('')
            alternatives.append((r,enabled));recipe_count+=1
            for a in r.operands:
                if a in initial:continue
                model.add_implication(enabled,selected[a])
                model.add(levels[v]>=levels[a]+1).only_enforce_if(enabled)
            model.add_hint(enabled,int(graph.get(v)==r))
        choices[v]=alternatives
        model.add(sum(enabled for _,enabled in alternatives)==selected[v])
        model.add_hint(selected[v],int(v in graph))
        model.add_hint(levels[v],depths.get(v,1))
    for t in set(puzzle.targets)-initial:model.add(selected[t]==1)
    cost=sum(selected.values())
    model.add(cost<=len(incumbent))
    model.minimize(cost)
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=seconds
    solver.parameters.num_search_workers=1
    solver.parameters.random_seed=130000
    status=solver.solve(model)
    info={'status':solver.status_name(status),'values':len(values),'recipes':recipe_count,
          'saved':0,'seconds':solver.wall_time}
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):return incumbent,info
    info.update(objective=solver.objective_value,bound=solver.best_objective_bound)
    if solver.objective_value>=len(incumbent):return incumbent,info
    chosen={v:r for v,options in choices.items() if solver.value(selected[v])
            for r,enabled in options if solver.value(enabled)}
    try:
        graph=close_graph(puzzle.targets,initial,chosen,{})
        candidate,_=schedule_with_search(puzzle,graph,len(incumbent)-1,attempts=24)
    except InvalidGraph:
        info['schedule_failed']=True
        return incumbent,info
    validate_program(puzzle,candidate)
    info['saved']=len(incumbent)-len(candidate)
    return candidate,info
