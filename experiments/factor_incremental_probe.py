import sys,json,time,math,random
from pathlib import Path
from functools import lru_cache
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0,str(Path.cwd()/'src'))
from tiny_solver import load_puzzles,read_submission,write_submission,validate_program
from recipe_graph_optimizer import Recipe,close_graph,schedule,InvalidGraph

SMALL=(2,3,5,7,11,13,17,19,23,29,31,37,41,43,47)
@lru_cache(maxsize=200000)
def factors(n):
    if n<2:return ()
    for p in SMALL:
        if n%p==0:return tuple(sorted((p,)+factors(n//p)))
    d=n-1;s=0
    while d%2==0:d//=2;s+=1
    probable=True
    for a in (2,3,5,7,11,13,17):
        if a>=n:continue
        x=pow(a,d,n)
        if x in (1,n-1):continue
        for _ in range(s-1):
            x=x*x%n
            if x==n-1:break
        else:probable=False;break
    if probable:return (n,)
    # A bounded exact-divisor search; unfactored composites are legal leaves.
    for c in (1,3,7):
        x=y=2
        for _ in range(400):
            x=(x*x+c)%n;y=(y*y+c)%n;y=(y*y+c)%n
            g=math.gcd(abs(x-y),n)
            if 1<g<n:return tuple(sorted(factors(g)+factors(n//g)))
            if g==n:break
    return (n,)

class Builder:
    def __init__(self,p,budget=3000):
        self.p=p;self.initial=set(p.starting_values);self.count=0;self.budget=budget
        self.memo={v:{} for v in self.initial}
    def add(self,g,v,op,a,b):
        if v not in self.initial and v not in g:g[v]=Recipe(op,a,b)
        return v
    def binary(self,n):
        if n in self.memo:return self.memo[n]
        if n==1:return {1:Recipe('/',self.p.starting_values[0],self.p.starting_values[0])}
        g=dict(self.binary(n//2));self.add(g,2*(n//2),'+',n//2,n//2)
        if n%2:g.update(self.binary(1));self.add(g,n,'+',n-1,1)
        return g
    def plan(self,n):
        if n in self.memo:return self.memo[n]
        self.count+=1
        if n==1 or self.count>self.budget:
            g=self.binary(n);self.memo[n]=g;return g
        best=self.binary(n)
        choices=[]
        for delta in (0,1,-1,2,-2,3,-3,4,-4):
            if abs(delta)>=n:continue
            m=n+delta
            if not 1<m<=self.p.value_limit:continue
            fs=factors(m)
            if len(fs)<=1 or max(fs)>=n:continue
            # Repeated factors are cheap to exponentiate and often shared.
            score=sum(((0 if v in self.initial else max(1,v.bit_length()-5)/3)+math.log2(c+1)) for v,c in Counter(fs).items())+(delta!=0)
            choices.append((score,delta,fs))
        for _,delta,fs in sorted(choices)[:3]:
            g={};items=[]
            for prime,exponent in Counter(fs).items():
                g.update(self.plan(prime));v=prime
                # Binary exponentiation, including reuse of repeated squares.
                powers={1:prime};k=1
                while k*2<=exponent:
                    v=self.add(g,v*v,'*',v,v);k*=2;powers[k]=v
                parts=[powers[k] for k in powers if exponent&k]
                v=parts.pop()
                for b in parts:v=self.add(g,v*b,'*',v,b)
                items.append(v)
            items.sort();v=items.pop()
            for b in items:v=self.add(g,v*b,'*',v,b)
            if delta:
                g.update(self.plan(abs(delta)))
                self.add(g,n,'-' if delta>0 else '+',v,abs(delta))
            if len(g)<len(best):best=g
        # Initial values act as free nearby anchors and factors.
        for a in self.p.starting_values:
            d=abs(n-a)
            if 0<d<n and d.bit_length()+2<n.bit_length():
                g=dict(self.plan(d));self.add(g,n,'+' if n>a else '-',a,d)
                if len(g)<len(best):best=g
            if a>1 and n%a==0:
                g=dict(self.plan(n//a));self.add(g,n,'*',a,n//a)
                if len(g)<len(best):best=g
        self.memo[n]=best;return best

def job(args):
    p,best=args;before=len(best);builder=Builder(p);g={};failure=None
    for t in sorted(p.targets):
        builder.initial=set(p.starting_values)|set(g)
        builder.memo={v:{} for v in builder.initial}
        builder.count=0
        part=builder.plan(t)
        for v,r in part.items():g.setdefault(v,r)
    try:
        graph=close_graph(p.targets,set(p.starting_values),g,{})
        if len(graph)<len(best):
            candidate,peak=schedule(p,graph,len(best)-1)
            validate_program(p,candidate)
            if len(candidate)<len(best):best=candidate
    except InvalidGraph as e:failure=str(e)
    return p.puzzle_id,best,{'id':p.puzzle_id,'before':before,'after':len(best),'saved':before-len(best),'nodes':len(g),'planned':builder.count,'failure':failure}

if __name__=='__main__':
    puzzles=load_puzzles(Path('data/puzzles.csv'));order,current=read_submission(Path('submissions/submission_target130k_radix.csv'))
    rows=[];started=time.monotonic()
    with ProcessPoolExecutor(max_workers=4) as pool:
        for id,prog,row in pool.map(job,((p,current[p.puzzle_id]) for p in puzzles[:20])):
            current[id]=prog;rows.append(row)
            if len(rows)%10==0:print(len(rows),sum(r['saved'] for r in rows),round(time.monotonic()-started,2),flush=True)
    write_submission(Path('submissions/submission_factor_incremental.csv'),order,current)
    Path('reports/factor_incremental.json').write_text(json.dumps({'seconds':time.monotonic()-started,'saved':sum(r['saved'] for r in rows),'puzzles':rows},indent=2))
