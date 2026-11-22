"""Deterministic-seed restarts of joint reduction, retaining validated improvements."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import random
import time

from joint_reduction_solver import build_graph
from recipe_graph_optimizer import InvalidGraph
from register_scheduler import schedule_with_search
from tiny_solver import load_puzzles, read_submission, write_submission, validate_program
from validate_submission import validate


def solve_job(job):
    puzzle, incumbent, restarts, seed = job
    rng = random.Random(f'{seed}:{puzzle.puzzle_id}')
    best = incumbent
    winner = None
    failures = 0
    started = time.process_time()
    for iteration in range(restarts):
        weight = rng.uniform(.1, .65)
        factor_mode = rng.choice((0,1,1,2))
        temperature = rng.uniform(.05,.65)
        order_window = rng.choice((1,1,1,2,3))
        trial_seed = rng.randrange(2**32)
        try:
            graph = build_graph(puzzle, weight, 0, factor_mode=factor_mode,
                                rng=random.Random(trial_seed), temperature=temperature,
                                order_window=order_window, reuse_graph=True)
            if len(graph) >= len(best):
                continue
            candidate, _ = schedule_with_search(puzzle, graph, len(best)-1, attempts=6)
        except InvalidGraph:
            failures += 1
            continue
        validate_program(puzzle, candidate)
        if len(candidate) < len(best):
            best = candidate
            winner = {'iteration':iteration,'weight':weight,'factor_mode':factor_mode,
                      'temperature':temperature,'order_window':order_window,'trial_seed':trial_seed}
    return puzzle.puzzle_id, best, {'id':puzzle.puzzle_id,'before':len(incumbent),'after':len(best),
            'saved':len(incumbent)-len(best),'winner':winner,'failures':failures,
            'cpu_seconds':round(time.process_time()-started,6)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--puzzles',type=Path,required=True)
    parser.add_argument('--current',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--restarts',type=int,default=32)
    parser.add_argument('--seed',type=int,default=130000)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--start-index',type=int,default=0)
    parser.add_argument('--end-index',type=int)
    args=parser.parse_args()
    puzzles=load_puzzles(args.puzzles)
    end=len(puzzles) if args.end_index is None else args.end_index
    if min(args.restarts,args.workers)<=0 or not 0<=args.start_index<=end<=len(puzzles):
        parser.error('invalid budget or range')
    if args.current.resolve()==args.output.resolve():
        parser.error('preserve the input checkpoint')
    base=validate(args.puzzles,args.current)
    order,selected=read_submission(args.current)
    rows=[]
    started=time.monotonic()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    def save(complete=False):
        temporary=args.output.with_suffix('.csv.tmp')
        write_submission(temporary,order,selected)
        temporary.replace(args.output)
        report={'optimizer':'randomized_joint_reduction','current':str(args.current),
                'output':str(args.output),'before':base['score'],'after':sum(map(len,selected.values())),
                'saved':sum(r['saved'] for r in rows),'improved':sum(r['saved']>0 for r in rows),
                'processed':len(rows),'complete':complete,'restarts':args.restarts,'seed':args.seed,
                'workers':args.workers,'start_index':args.start_index,'end_index':end,
                'wall_seconds':time.monotonic()-started,'puzzles':rows}
        if complete:report['validation']=validate(args.puzzles,args.output)
        temporary=args.report.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report,indent=2)+'\n')
        temporary.replace(args.report)
        return report
    jobs=((p,selected[p.puzzle_id],args.restarts,args.seed) for p in puzzles[args.start_index:end])
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for puzzle_id,candidate,info in pool.map(solve_job,jobs):
            selected[puzzle_id]=candidate;rows.append(info)
            if len(rows)%10==0:
                print(json.dumps({'processed':len(rows),'saved':sum(r['saved'] for r in rows),
                                  'seconds':round(time.monotonic()-started,2)}),flush=True)
            if len(rows)%100==0:save()
    report=save(True)
    print(json.dumps({k:v for k,v in report.items() if k!='puzzles'},indent=2))


if __name__=='__main__':
    main()
