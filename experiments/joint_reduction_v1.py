"""Joint backward reduction by differences, exact quotients and remainders.

The working set contains values still required by any output. A dependency
already in that set has zero marginal construction estimate. Each reduction
replaces the largest outstanding value, paying for new operands and operations.
The estimate ranks alternatives only: final selection uses emitted instruction
counts and independent arithmetic replay. No constants are introduced for free.
"""
from functools import lru_cache
import time
from recipe_graph_optimizer import Recipe, close_graph, schedule, InvalidGraph
from short_synthesis_optimizer import one_step_recipes
from signed_digit_solver import choose_digits
from tiny_solver import validate_program

def build_graph(p, weight, metric, extended=False):
 initial=set(p.starting_values);needed=set(p.targets)-initial;g={}
 one=one_step_recipes(initial,p.value_limit)
 seed_bases=[1,2,4,8,16,32,64,128,256]
 if extended:
  seed_bases=sorted(set(seed_bases+[1<<k for k in range(12,p.value_limit.bit_length(),4)]+list(one)))
 @lru_cache(maxsize=None)
 def estimate(v):
  if extended and v in one:return min(1,v.bit_length()*weight)
  if metric==0:return v.bit_length()*weight
  return len(choose_digits(v,p.value_limit))*weight
 def cost(v):
  if v in initial or v in needed or v in g:return 0
  return estimate(v)
 while needed:
  n=max(needed);needed.remove(n)
  if n in g:continue
  if n==1:
   g[1]=Recipe('/',p.starting_values[0],p.starting_values[0]);continue
  if n in one:
   op,a,b,_=one[n];g[n]=Recipe(op,a,b);continue
  anchors=sorted((needed|initial)-{1})
  # A power-of-two seed is an option, but must itself be constructed.
  anchors=sorted(set(anchors+seed_bases+([v for v in g if v<n] if extended else []))-{n})
  choices=[]
  for a in anchors:
   if a>=2*n or a>p.value_limit:continue
   d=abs(n-a)
   if d and d<n:
    patch={n:Recipe('+' if n>a else '-',a,d)}
    choices.append((1+cost(a)+cost(d),len(patch),d,patch))
   if a>=n:continue
   q,r=divmod(n,a)
   for q,r,op in ((q,r,'+'),(q+1,a-r,'-')):
    if not r:
     patch={n:Recipe('*',a,q)}
     choices.append((1+cost(a)+cost(q),1,0,patch));continue
    product=q*a
    if product>p.value_limit or product in g or q>=n:continue
    patch={product:Recipe('*',a,q),n:Recipe(op,product,r)}
    # Multiplication by one disappears.
    if q==1:
     patch={n:Recipe(op,a,r)}
    choices.append((len(patch)+cost(a)+cost(q)*(q!=1)+cost(r),len(patch),r,patch))
  if not choices:
   raise RuntimeError('no reduction')
  _,_,_,patch=min(choices,key=lambda x:x[:3])
  for v,recipe in patch.items():
   if v not in initial:g[v]=recipe
  for recipe in patch.values():
   for v in recipe.operands:
    if v not in initial and v not in g:needed.add(v)
  if len(g)>4000:raise InvalidGraph('too many nodes')
 return close_graph(p.targets,initial,g,{})

def solve_job(args):
 p,best,extended_options=args;before=len(best);win=None;failures=0;minnodes=10**9
 started=time.process_time()
 for extended in extended_options:
  for metric,weights in ((0,(.1,.2,.35,.6)),(1,(.5,1,2))):
   for weight in weights:
    try:
     g=build_graph(p,weight,metric,extended);minnodes=min(minnodes,len(g))
     if len(g)>=len(best):continue
     candidate,peak=schedule(p,g,len(best)-1)
    except InvalidGraph:failures+=1;continue
    validate_program(p,candidate)
    if len(candidate)<len(best):best=candidate;win=(weight,metric,extended)
 return p.puzzle_id,best,dict(id=p.puzzle_id,before=before,after=len(best),saved=before-len(best),parameters=win,failures=failures,minnodes=minnodes,cpu_seconds=round(time.process_time()-started,6))


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
    parser.add_argument('--start-index', type=int, default=0)
    parser.add_argument('--end-index', type=int)
    args = parser.parse_args()
    puzzles = load_puzzles(args.puzzles)
    end = len(puzzles) if args.end_index is None else args.end_index
    if not 0 <= args.start_index <= end <= len(puzzles):
        parser.error('invalid puzzle range')
    if args.workers <= 0:
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
                  'complete': complete, 'wall_seconds': round(time.monotonic() - started, 3),
                  'puzzles': rows}
        if complete:
            report['validation'] = validate(args.puzzles, args.output)
        temporary = args.report.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(args.report)
        return report
    jobs = ((p, selected[p.puzzle_id], (False, True) if args.extended else (False,))
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
