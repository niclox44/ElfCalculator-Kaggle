import sys,json,time
from pathlib import Path
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0,str(Path.cwd()/'src'))
from tiny_solver import load_puzzles,read_submission,write_submission,validate_program
from signed_digit_solver import choose_digits,binary_digits
from recipe_graph_optimizer import Recipe,close_graph,schedule,InvalidGraph
from deep_anchor_solver import anchor_layers

def build(p,depth,signed,style):
    initial=set(p.starting_values);graph={}
    def put(v,op,a,b):
        if v not in initial and v not in graph:graph[v]=Recipe(op,a,b)
        return v
    if 1 not in initial:put(1,'/',p.starting_values[0],p.starting_values[0])
    if depth:
        plans,sets=anchor_layers(p,depth);leaves=sets[-1]
    else:plans=[];leaves=set(p.targets)
    expressions={t:Counter({(1<<b)*sign:1 for b,sign in (choose_digits(t,p.value_limit) if signed else binary_digits(t)).items()}) for t in sorted(leaves-initial)}
    highest=max((abs(a) for e in expressions.values() for a in e),default=1)
    power=2
    while power<=highest:
        put(power,'+',power//2,power//2);power*=2
    for iteration in range(1000):
        pairs=Counter()
        for e in expressions.values():
            terms=sorted(e)
            for i,a in enumerate(terms):
                for b in terms[i+1:]:
                    v=a+b
                    if not v or abs(v)>p.value_limit:continue
                    # Canonical sign so opposite occurrences share one value.
                    pair=(a,b) if v>0 else (-b,-a)
                    pairs[pair]+=min(e[a],e[b])
        if not pairs:break
        def priority(pair):
            a,b=pair;v=a+b
            saving=pairs[pair]-(v not in graph and v not in initial)
            return (saving, pairs[pair], -v.bit_length() if style==0 else v.bit_length(), -v)
        pair=max(pairs,key=priority)
        if priority(pair)[0]<=0:break
        a,b=pair;v=a+b
        if v not in initial and v not in graph:
            if a>0 and b>0:put(v,'+',a,b)
            elif a<0:put(v,'-',b,-a)
            else:put(v,'-',a,-b)
        for e in expressions.values():
            for sign in (1,-1):
                x,y=sign*a,sign*b
                count=min(e[x],e[y])
                if count:
                    e[x]-=count;e[y]-=count;e[sign*v]+=count
                    if not e[x]:del e[x]
                    if not e[y]:del e[y]
    for target,e in expressions.items():
        positives=sorted([v for v,c in e.items() if v>0 for _ in range(c)],reverse=True)
        negatives=sorted([-v for v,c in e.items() if v<0 for _ in range(c)],reverse=True)
        current=positives.pop(0)
        # Subtract when possible to keep intermediate values under the limit.
        while positives or negatives:
            if negatives and current>negatives[-1]:
                operand=negatives.pop();current=put(current-operand,'-',current,operand)
            else:
                operand=positives.pop();current=put(current+operand,'+',current,operand)
            if current>p.value_limit:raise InvalidGraph('limit')
        assert current==target
    for plan in reversed(plans):
        for target,relation in plan.items():
            if relation is not None:
                anchor,delta=relation
                put(target,'+' if target>anchor else '-',anchor,delta)
    return close_graph(p.targets,initial,graph,{})

def job(args):
    p,best=args;before=len(best);win=None;failures=0
    for depth in (0,1,2,3):
        for signed in (False,True):
            for style in (0,1):
                try:
                    g=build(p,depth,signed,style)
                    if len(g)>=len(best):continue
                    candidate,peak=schedule(p,g,len(best)-1)
                except (InvalidGraph,IndexError):failures+=1;continue
                validate_program(p,candidate)
                if len(candidate)<len(best):best=candidate;win=(depth,signed,style)
    return p.puzzle_id,best,{'id':p.puzzle_id,'before':before,'after':len(best),'saved':before-len(best),'parameters':win,'failures':failures}

if __name__=='__main__':
    puzzles=load_puzzles(Path('data/puzzles.csv'));order,current=read_submission(Path('submissions/submission_target130k_radix.csv'))
    rows=[];started=time.monotonic()
    with ProcessPoolExecutor(max_workers=8) as pool:
        for id,prog,row in pool.map(job,((p,current[p.puzzle_id]) for p in puzzles[:100])):
            current[id]=prog;rows.append(row)
            if len(rows)%10==0:print(len(rows),sum(r['saved'] for r in rows),round(time.monotonic()-started,2),flush=True)
    out=Path('submissions/submission_shared_probe.csv');write_submission(out,order,current)
    Path('reports/shared_probe.json').write_text(json.dumps({'seconds':time.monotonic()-started,'saved':sum(r['saved'] for r in rows),'puzzles':rows},indent=2))
