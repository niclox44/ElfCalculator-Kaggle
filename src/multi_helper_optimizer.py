"""Replace several consumers through a shared helper requiring two new operations.

The complete closed graph determines the saving, including the construction of
both helper nodes. Source and replacement dependencies are checked for cycles.
"""
from collections import defaultdict
import time
from recipe_graph_optimizer import Recipe, InvalidGraph, close_graph, extract_recipes
from short_synthesis_optimizer import inverse_partners
from register_scheduler import schedule_with_search
from tiny_solver import validate_program


def optimize_multi_helper(puzzle, incumbent, limit=256, seconds=5, proposal_sink=None, slack=0):
    deadline=time.process_time()+seconds
    initial=set(puzzle.starting_values)
    _,seed=extract_recipes(puzzle,incumbent)
    graph=close_graph(puzzle.targets,initial,seed,{})
    values=sorted(initial)+list(graph)
    masks={v:0 for v in initial}
    bits={v:1<<i for i,v in enumerate(graph)}
    for v,r in graph.items():masks[v]=bits[v]|masks[r.left]|masks[r.right]
    pairs={}
    for i,a in enumerate(values):
        for b in values[:i+1]:
            options=[(a+b,'+',a,b),(a*b,'*',a,b)]
            if a!=b:options.append((abs(a-b),'-',max(a,b),min(a,b)))
            if a%b==0:options.append((a//b,'/',a,b))
            elif b%a==0:options.append((b//a,'/',b,a))
            for v,op,left,right in options:
                if not 0<v<=puzzle.value_limit or v in masks:continue
                support=masks[a]|masks[b]
                if v not in pairs or support.bit_count()<pairs[v][1].bit_count():
                    pairs[v]=(Recipe(op,left,right),support)
    uses=defaultdict(dict)
    scores=defaultdict(int)
    for root in graph:
        for b in values:
            if masks[b]&bits[root]:continue
            for w,op,left,right in inverse_partners(root,b,puzzle.value_limit):
                if w in masks:continue
                possible=(masks[root]&~(bits[root]|masks[b])).bit_count()
                if possible==0:continue
                old=uses[w].get(root)
                if old is None or possible>old[0]:
                    uses[w][root]=(possible,Recipe(op,left,right),masks[b])
                    scores[w]+=possible-(old[0] if old else 0)
    candidates=sorted((w for w in uses if len(uses[w])>=2 and scores[w]>2),
                      key=lambda w:(-scores[w],-len(uses[w]),w))[:limit]
    best=incumbent
    tested=0;closed=0;improvements=0
    for w in candidates:
        if time.process_time()>=deadline:break
        constructions=[]
        if w in pairs:
            recipe,support=pairs[w]
            constructions.append(({w:recipe},support))
        for a in values:
            for q,op,left,right in inverse_partners(w,a,puzzle.value_limit):
                if q not in pairs or q==w:continue
                first,support=pairs[q]
                support|=masks[a]
                constructions.append(({q:first,w:Recipe(op,left,right)},support))
        constructions.sort(key=lambda item:item[1].bit_count())
        for patch,support in constructions[:32]:
            rewritten={root:r for root,(_,r,_) in uses[w].items() if not support&bits[root]}
            if len(rewritten)<2:continue
            tested+=1
            try:trial=close_graph(puzzle.targets,initial,graph|patch|rewritten,{})
            except InvalidGraph:continue
            closed+=1
            if proposal_sink is not None and len(trial)<=len(graph)+slack:
                for value,recipe in (patch|rewritten).items():
                    proposal_sink[value].add(recipe)
            if len(trial)>=len(best):continue
            try:program,_=schedule_with_search(puzzle,trial,len(best)-1,attempts=12)
            except InvalidGraph:continue
            validate_program(puzzle,program)
            if len(program)<len(best):best=program;improvements+=1
    return best,{'candidate_helpers':len(candidates),'tested':tested,'closed':closed,
                 'improvements':improvements,'saved':len(incumbent)-len(best),
                 'budget_exhausted':time.process_time()>=deadline}
