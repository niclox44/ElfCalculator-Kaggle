"""Run the extended attributed DAG optimizer and independently replay improvements."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import time

from tiny_solver import load_puzzles, read_submission, write_submission, validate_program
from validate_submission import validate

ROOT = Path(__file__).resolve().parents[1]


def solve_job(job):
    puzzle, incumbent, configs, timeout = job
    best = incumbent
    trials = []
    for config in configs:
        started = time.monotonic()
        payload = f'P {puzzle.puzzle_id} {len(puzzle.starting_values)} '
        payload += ' '.join(map(str,puzzle.starting_values))
        payload += f' {len(puzzle.targets)} ' + ' '.join(map(str,puzzle.targets))
        payload += f' {puzzle.value_limit} {puzzle.registers} {len(best)}\n'
        payload += '\n'.join(' '.join(map(str,op)) for op in best)+'\n'
        info = {'config':config,'before':len(best)}
        try:
            result = subprocess.run([str(ROOT/'build/elfopt_extended'),*map(str,config)],
                                    input=payload,text=True,capture_output=True,
                                    check=True,timeout=timeout)
            info['diagnostics'] = result.stderr[-1200:]
            lines = result.stdout.strip().splitlines()
            if lines:
                tag, identifier, previous, count = lines[0].split()
                if tag!='R' or identifier!=puzzle.puzzle_id or int(previous)!=len(best):
                    raise ValueError('invalid native output header')
                candidate = [[line.split()[0],*map(int,line.split()[1:])] for line in lines[1:]]
                if len(candidate)!=int(count):raise ValueError('truncated native output')
                validate_program(puzzle,candidate)
                info['candidate'] = len(candidate)
                if len(candidate)<len(best):best=candidate
        except (subprocess.SubprocessError,ValueError,AssertionError) as error:
            info['failure']=str(error)[:300]
        info['seconds']=round(time.monotonic()-started,3)
        trials.append(info)
    return puzzle.puzzle_id,best,{'id':puzzle.puzzle_id,'before':len(incumbent),
                                 'after':len(best),'saved':len(incumbent)-len(best),
                                 'trials':trials}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('puzzles', 'current', 'output', 'report'):
        parser.add_argument('--'+flag, type=Path, required=True)
    parser.add_argument('--configs', default='[["--time",8,"--seed",130000,"--eq",0.4]]',
                        help='JSON array of native CLI argument arrays')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--start-index', type=int, default=0)
    parser.add_argument('--end-index', type=int)
    args = parser.parse_args()
    configs = json.loads(args.configs)
    source_hash = hashlib.sha256((ROOT/'native/elfopt_extended.cpp').read_bytes()).hexdigest()
    binary_hash = hashlib.sha256((ROOT/'build/elfopt_extended').read_bytes()).hexdigest()
    puzzles = load_puzzles(args.puzzles)
    end = len(puzzles) if args.end_index is None else args.end_index
    if args.current.resolve() == args.output.resolve():
        parser.error('preserve the input checkpoint')
    if not configs or args.timeout <= 0 or args.workers <= 0 or not 0<=args.start_index<=end<=len(puzzles):
        parser.error('invalid budget or range')
    base = validate(args.puzzles, args.current)
    order, selected = read_submission(args.current)
    rows = []
    started = time.monotonic()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    def save(complete=False):
        temporary = args.output.with_suffix('.csv.tmp')
        write_submission(temporary, order, selected)
        temporary.replace(args.output)
        report = {'optimizer': 'extended_pair_dag_lns', 'current': str(args.current),
                  'output': str(args.output), 'before': base['score'],
                  'after': sum(map(len,selected.values())), 'saved': sum(r['saved'] for r in rows),
                  'processed': len(rows), 'complete': complete, 'configs': configs,
                  'improved': sum(r['saved']>0 for r in rows),
                  'start_index': args.start_index, 'end_index': end,
                  'source': 'native/elfopt_extended.cpp',
                  'source_sha256': source_hash, 'binary_sha256': binary_hash,
                  'workers': args.workers, 'timeout': args.timeout,
                  'wall_seconds': time.monotonic()-started, 'puzzles': rows}
        if complete:
            report['validation'] = validate(args.puzzles,args.output)
        temporary = args.report.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report,indent=2)+'\n')
        temporary.replace(args.report)
        return report
    jobs = ((p,selected[p.puzzle_id],configs,args.timeout) for p in puzzles[args.start_index:end])
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for puzzle_id, candidate, info in pool.map(solve_job,jobs):
            selected[puzzle_id] = candidate
            rows.append(info)
            if len(rows)%10 == 0:
                print(json.dumps({'processed':len(rows),'saved':sum(r['saved'] for r in rows),
                                  'seconds':round(time.monotonic()-started,2)}),flush=True)
            if len(rows)%100 == 0:
                save()
    report = save(True)
    print(json.dumps({k:v for k,v in report.items() if k!='puzzles'},indent=2))


if __name__ == '__main__':
    main()
