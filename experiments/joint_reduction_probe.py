import sys,json,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0,str(Path.cwd()/'src'))
from tiny_solver import load_puzzles,read_submission,write_submission,validate_program
from recipe_graph_optimizer import Recipe,close_graph,schedule,InvalidGraph
from signed_digit_solver import choose_digits

def build(p,weight,metric):
 initial=set(p.starting_values);needed=set(p.targets)-initial;g={}
 def cost(v):
  if v in initial or v in needed or v in g:return 0
  if metric==0:return v.bit_length()*weight
  return len(choose_digits(v,p.value_limit))*weight
 while needed:
  n=max(needed);needed.remove(n)
  if n in g:continue
  if n==1:
   g[1]=Recipe('/',p.starting_values[0],p.starting_values[0]);continue
  anchors=sorted((needed|initial)-{1})
  # A power-of-two seed is an option, but must itself be constructed.
  anchors=sorted(set(anchors+[1,2,4,8,16,32,64,128,256])-{n})
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

def job(args):
 p,best=args;before=len(best);win=None;failures=0;minnodes=10**9
 for metric,weights in ((0,(.1,.2,.35,.6)),(1,(.5,1,2))):
  for weight in weights:
   try:
    g=build(p,weight,metric);minnodes=min(minnodes,len(g))
    if len(g)>=len(best):continue
    candidate,peak=schedule(p,g,len(best)-1)
   except InvalidGraph:failures+=1;continue
   validate_program(p,candidate)
   if len(candidate)<len(best):best=candidate;win=(weight,metric)
 return p.puzzle_id,best,dict(id=p.puzzle_id,before=before,after=len(best),saved=before-len(best),parameters=win,failures=failures,minnodes=minnodes)

if __name__=='__main__':
 puzzles=load_puzzles(Path('data/puzzles.csv'));order,current=read_submission(Path('submissions/submission_target130k_radix.csv'))
 rows=[];started=time.monotonic()
 with ProcessPoolExecutor(max_workers=4) as pool:
  for id,prog,row in pool.map(job,((p,current[p.puzzle_id]) for p in puzzles[:100])):
   current[id]=prog;rows.append(row)
   if len(rows)%10==0:print(len(rows),sum(r['saved'] for r in rows),round(time.monotonic()-started,2),flush=True)
 write_submission(Path('submissions/submission_difference_probe.csv'),order,current)
 Path('reports/difference_probe.json').write_text(json.dumps({'seconds':time.monotonic()-started,'saved':sum(r['saved'] for r in rows),'puzzles':rows},indent=2))
