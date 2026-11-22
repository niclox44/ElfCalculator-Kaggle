import sys,json,time,inspect
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from math import gcd
sys.path.insert(0,str(Path.cwd()/'src'))
from tiny_solver import load_puzzles,read_submission,write_submission,validate_program
from joint_reduction_solver import build_graph
from short_synthesis_optimizer import one_step_recipes
from signed_digit_solver import choose_digits
from register_scheduler import schedule_with_search
from recipe_graph_optimizer import Recipe,InvalidGraph,close_graph
from validate_submission import validate
source=inspect.getsource(build_graph).replace('def build_graph(', 'def build_pair_graph(')
insert='''  ready=sorted(needed|initial)
  for i,a in enumerate(ready):
   for b in ready[:i+1]:
    candidates=[(a+b,'+',a,b),(a*b,'*',a,b)]
    if a!=b:candidates.append((abs(a-b),'-',max(a,b),min(a,b)))
    for c,op,left,right in candidates:
     if not 0<c<=p.value_limit or c>=2*n:continue
     if c in g and c>n:continue
     r=abs(n-c)
     if not r:
      patch={n:Recipe(op,left,right)}
      choices.append((1,1,0,patch));continue
     if r>=n:continue
     patch={n:Recipe('+' if n>c else '-',c,r)}
     if c not in initial and c not in needed and c not in g:
      patch[c]=Recipe(op,left,right)
     choices.append((len(patch)+cost(r),len(patch),r,patch))
'''
source=source.replace('  if not choices:',insert+'  if not choices:')
exec(source)

def job(args):
 p,best=args;before=len(best);win=None;failures=0
 for fm in (0,1):
  for weight in (.15,.25,.4,.65):
   try:
    g=build_pair_graph(p,weight,0,factor_mode=fm)
    if len(g)>=len(best):continue
    candidate,peak=schedule_with_search(p,g,len(best)-1,attempts=18)
   except InvalidGraph:failures+=1;continue
   validate_program(p,candidate)
   if len(candidate)<len(best):best=candidate;win=(weight,fm)
 return p.puzzle_id,best,dict(id=p.puzzle_id,before=before,after=len(best),saved=before-len(best),parameters=win,failures=failures)

if __name__=='__main__':
 puzzles=load_puzzles(Path('data/puzzles.csv'));order,current=read_submission(Path('submissions/submission_joint_cleanup_synthesis_first.csv'))
 rows=[];started=time.monotonic()
 with ProcessPoolExecutor(max_workers=8) as pool:
  for id,prog,row in pool.map(job,((p,current[p.puzzle_id]) for p in puzzles[:100])):
   current[id]=prog;rows.append(row)
   if len(rows)%10==0:print(len(rows),sum(r['saved'] for r in rows),round(time.monotonic()-started,2),flush=True)
 out=Path('submissions/submission_pair_joint_probe.csv');write_submission(out,order,current)
 Path('reports/pair_joint_probe.json').write_text(json.dumps({'seconds':time.monotonic()-started,'validation':validate(Path('data/puzzles.csv'),out),'saved':sum(r['saved'] for r in rows),'puzzles':rows},indent=2))
