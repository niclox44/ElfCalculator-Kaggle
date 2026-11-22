import sys,json,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0,str(Path.cwd()/'src'))
from tiny_solver import load_puzzles,read_submission,write_submission
from beam_joint_solver import optimize_beam
from validate_submission import validate

def job(args):
 p,old=args;best,info=optimize_beam(p,old,budget=6,width=16)
 return p.puzzle_id,best,dict(id=p.puzzle_id,before=len(old),after=len(best),saved=len(old)-len(best),**info)
if __name__=='__main__':
 puzzles=load_puzzles(Path('data/puzzles.csv'));order,current=read_submission(Path('submissions/submission_joint_best.csv'))
 rows=[];started=time.monotonic()
 with ProcessPoolExecutor(max_workers=8) as pool:
  for id,prog,row in pool.map(job,((p,current[p.puzzle_id]) for p in puzzles[:100])):
   current[id]=prog;rows.append(row)
   if len(rows)%10==0:print(len(rows),sum(r['saved'] for r in rows),round(time.monotonic()-started,2),flush=True)
 out=Path('submissions/submission_beam_joint_probe.csv');write_submission(out,order,current)
 Path('reports/beam_joint_probe.json').write_text(json.dumps({'seconds':time.monotonic()-started,'validation':validate(Path('data/puzzles.csv'),out),'saved':sum(r['saved'] for r in rows),'puzzles':rows},indent=2))
