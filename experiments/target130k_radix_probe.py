"""Reproduce the radix probe from the repository root.

Input: saved target130k pilot; outputs: target130k_radix submission and report.
Tests both unsigned and balanced remainders over fixed bases and starting values.
Shares repeated numeric components; uses existing scheduling and validation.
This is a bounded experiment, not a proof of optimality.
"""
import sys,json,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0,str(Path.cwd()/'src'))
from tiny_solver import load_puzzles,read_submission,write_submission,validate_program
from recipe_graph_optimizer import Recipe,close_graph,schedule,InvalidGraph
from validate_submission import validate

def graph_for(p,base,signed):
    initial=set(p.starting_values); recipes={}; known=set(initial)
    def put(v,op,a,b):
        if v not in known:
            recipes[v]=Recipe(op,a,b);known.add(v)
        return v
    def binary(v):
        if v in known:return v
        if v==1:return put(1,'/',p.starting_values[0],p.starting_values[0])
        q=binary(v//2); doubled=put(q*2,'+',q,q)
        if v%2: return put(v,'+',doubled,binary(1))
        return doubled
    def build(v):
        if v in known:return v
        if v<=base:return binary(v)
        q,r=divmod(v,base);neg=False
        if signed and r>base//2 and (q+1)*base<=p.value_limit:
            q+=1;r=base-r;neg=True
        a=build(q);b=binary(base)
        product=put(q*base,'*',a,b)
        if not r:return product
        d=build(r)
        return put(v,'-' if neg else '+',product,d)
    for t in sorted(p.targets):build(t)
    return close_graph(p.targets,initial,recipes,{})

def job(args):
    p,best=args;before=len(best);wins=None;failures=0
    bases=sorted(set([4,6,8,10,12,16,24,32,48,64,96,128,192,256,512,1024]+[v for v in p.starting_values if 2<=v<=2048]))
    for base in bases:
        if base>p.value_limit:continue
        for signed in [False,True]:
            g=graph_for(p,base,signed)
            if len(g)>=len(best):continue
            try:
                result=schedule(p,g,len(best)-1)
            except InvalidGraph:
                failures+=1;continue
            candidate,peak=result
            validate_program(p,candidate)
            if len(candidate)<len(best):best=candidate;wins=(base,signed)
    return p.puzzle_id,best,{'id':p.puzzle_id,'before':before,'after':len(best),'saved':before-len(best),'parameters':wins,'failures':failures}

if __name__=='__main__':
    puzzles=load_puzzles(Path('data/puzzles.csv'));order,current=read_submission(Path('submissions/submission_target130k_pilot_synthesis_first.csv'))
    rows=[];t=time.monotonic()
    with ProcessPoolExecutor(max_workers=8) as pool:
        for id,prog,row in pool.map(job,((p,current[p.puzzle_id]) for p in puzzles)):
            current[id]=prog;rows.append(row)
            if len(rows)%100==0:print(len(rows),sum(r['saved'] for r in rows),round(time.monotonic()-t,2),flush=True)
    out=Path('submissions/submission_target130k_radix.csv');write_submission(out,order,current)
    report={'validation':validate(Path('data/puzzles.csv'),out),'before':sum(r['before'] for r in rows),'saved':sum(r['saved'] for r in rows),'improved':sum(r['saved']>0 for r in rows),'seconds':time.monotonic()-t,'puzzles':rows}
    Path('reports/target130k_radix_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='puzzles'},indent=2))
