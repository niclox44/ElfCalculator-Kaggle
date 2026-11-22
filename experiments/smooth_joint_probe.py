import sys,json,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0,str(Path.cwd()/'src'))
from tiny_solver import load_puzzles,read_submission,write_submission,validate_program
from joint_reduction_solver import build_graph
from register_scheduler import schedule_with_search
from recipe_graph_optimizer import InvalidGraph
from validate_submission import validate

def job(args):
 p,best=args;before=len(best);win=None;failures=0
 for fm in (0,1):
  for weight in (.15,.25,.4,.65):
   try:
    g=build_graph(p,weight,0,factor_mode=fm,smooth_mode=True)
    if len(g)>=len(best):continue
    candidate,peak=schedule_with_search(p,g,len(best)-1,attempts=18)
   except InvalidGraph:failures+=1;continue
   validate_program(p,candidate)
   if len(candidate)<len(best):best=candidate;win=(weight,fm)
 return p.puzzle_id,best,dict(id=p.puzzle_id,before=before,after=len(best),saved=before-len(best),parameters=win,failures=failures)

if __name__=='__main__':
 puzzles=load_puzzles(Path('data/puzzles.csv'));order,current=read_submission(Path('submissions/submission_joint_best.csv'))
 rows=[];started=time.monotonic()
 with ProcessPoolExecutor(max_workers=8) as pool:
  for id,prog,row in pool.map(job,((p,current[p.puzzle_id]) for p in puzzles[:100])):
   current[id]=prog;rows.append(row)
   if len(rows)%10==0:print(len(rows),sum(r['saved'] for r in rows),round(time.monotonic()-started,2),flush=True)
 out=Path('submissions/submission_smooth_joint_probe.csv');write_submission(out,order,current)
 Path('reports/smooth_joint_probe.json').write_text(json.dumps({'seconds':time.monotonic()-started,'validation':validate(Path('data/puzzles.csv'),out),'saved':sum(r['saved'] for r in rows),'puzzles':rows},indent=2))
