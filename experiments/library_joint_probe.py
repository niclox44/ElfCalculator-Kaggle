import sys,json,time
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0,str(Path.cwd()/'src'))
from tiny_solver import load_puzzles,read_submission,write_submission,validate_program
from short_synthesis_optimizer import one_step_recipes
from recipe_graph_optimizer import Recipe,InvalidGraph,close_graph
from register_scheduler import schedule_with_search
from validate_submission import validate


def library(p):
 initial=set(p.starting_values)
 first=one_step_recipes(initial,p.value_limit)
 entries={v:{v:Recipe(op,a,b)} for v,(op,a,b,_) in first.items()}
 def ops(a,b):
  yield a+b,'+',a,b
  if a*b<=p.value_limit:yield a*b,'*',a,b
  if a!=b:yield abs(a-b),'-',max(a,b),min(a,b)
  if a%b==0:yield a//b,'/',a,b
  elif b%a==0:yield b//a,'/',b,a
 def insert(v,op,a,b,patch):
  if not 0<v<=p.value_limit or v in initial or v in patch:return
  if v in entries and len(entries[v])<=len(patch)+1:return
  entries[v]=patch|{v:Recipe(op,a,b)}
 for a,patch in list(entries.items()):
  for b in initial:
   for v,op,x,y in ops(a,b):insert(v,op,x,y,patch)
  for v,op,x,y in ops(a,a):insert(v,op,x,y,patch)
 seconds=dict(entries)
 for a,patch in seconds.items():
  for b in initial|set(patch):
   for v,op,x,y in ops(a,b):insert(v,op,x,y,patch)
 firstvalues=sorted(first)
 for i,a in enumerate(firstvalues):
  for b in firstvalues[:i]:
   patch=seconds[a]|seconds[b]
   for v,op,x,y in ops(a,b):insert(v,op,x,y,patch)
 return entries

# Use the checked reduction algorithm, adding exact short constructions as options.
from joint_reduction_solver import build_graph as original_build
import inspect
source=inspect.getsource(original_build)
source=source.replace('def build_graph(p, weight, metric, extended=False, factor_mode=0):','def build_library_graph(p, weight, metric, lib, extended=False, factor_mode=0):')
source=source.replace('  if metric==0:return v.bit_length()*weight','  if metric==0:return min(v.bit_length()*weight,len(lib.get(v,{})) or 1000000)')
source=source.replace('  choices=[]','  choices=[]\n  if n in lib:\n   patch=lib[n]\n   marginal=len(set(patch)-initial-set(g)-needed)\n   choices.append((marginal,len(patch),0,patch))')
from functools import lru_cache
from math import gcd
from signed_digit_solver import choose_digits
exec(source)

def job(args):
 p,best=args;before=len(best);lib=library(p);win=None;failures=0
 for fm in (0,1):
  for weight in (.15,.25,.4,.65):
   try:
    g=build_library_graph(p,weight,0,lib,factor_mode=fm)
    if len(g)>=len(best):continue
    candidate,peak=schedule_with_search(p,g,len(best)-1,attempts=18)
   except InvalidGraph:failures+=1;continue
   validate_program(p,candidate)
   if len(candidate)<len(best):best=candidate;win=(weight,fm)
 return p.puzzle_id,best,dict(id=p.puzzle_id,before=before,after=len(best),saved=before-len(best),parameters=win,failures=failures,library_size=len(lib))

if __name__=='__main__':
 puzzles=load_puzzles(Path('data/puzzles.csv'));order,current=read_submission(Path('submissions/submission_joint_cleanup_synthesis_first.csv'))
 rows=[];started=time.monotonic()
 with ProcessPoolExecutor(max_workers=6) as pool:
  for id,prog,row in pool.map(job,((p,current[p.puzzle_id]) for p in puzzles[:100])):
   current[id]=prog;rows.append(row)
   if len(rows)%10==0:print(len(rows),sum(r['saved'] for r in rows),round(time.monotonic()-started,2),flush=True)
 out=Path('submissions/submission_library_joint_probe.csv');write_submission(out,order,current)
 Path('reports/library_joint_probe.json').write_text(json.dumps({'seconds':time.monotonic()-started,'validation':validate(Path('data/puzzles.csv'),out),'saved':sum(r['saved'] for r in rows),'puzzles':rows},indent=2))
