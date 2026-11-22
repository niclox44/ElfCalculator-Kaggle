"""Measure joint Boolean recipe selection on the frozen public v89 portfolio."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from concurrent.futures import ProcessPoolExecutor
import json,time
from cpsat_recipe_optimizer import optimize_cpsat
from tiny_solver import load_puzzles,read_submission,write_submission
from validate_submission import validate


def job(args):
    p,program,donors=args
    result,info=optimize_cpsat(p,program,donors,seconds=8,harvest_helpers=True)
    return p.puzzle_id,result,info


if __name__=='__main__':
    puzzles=load_puzzles(Path('data/puzzles.csv'))
    order,base=read_submission(Path('submissions/submission_public_v89.csv'))
    donors=[read_submission(Path(p))[1] for p in [
        'submissions/submission_dictionary_base.csv',
        'third_party/santa_dictionary/reference_132515.csv',
        'submissions/submission_joint_factors.csv',
        'submissions/submission_joint_reduction.csv']]
    selected=dict(base);rows=[];start=time.monotonic()
    with ProcessPoolExecutor(max_workers=8) as pool:
        for pid,program,info in pool.map(job,[(p,base[p.puzzle_id],[d[p.puzzle_id] for d in donors]) for p in puzzles[:40]]):
            selected[pid]=program;rows.append(dict(id=pid,**info))
            if len(rows)%10==0:print(len(rows),sum(r['saved'] for r in rows),round(time.monotonic()-start,2),flush=True)
    path=Path('submissions/submission_cpsat_helpers_public_pilot.csv')
    write_submission(path,order,selected)
    validation=validate(Path('data/puzzles.csv'),path)
    report={'validation':validation,'seconds':time.monotonic()-start,'puzzles':rows}
    Path('reports/cpsat_helpers_public_pilot.json').write_text(json.dumps(report,indent=2)+'\n')
    print(validation)
