"""Run attributed Apache-2.0 dictionary construction and validate improvements."""
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
        mode = int(config[5]) if len(config) > 5 else 1
        if puzzle.registers != 48:
            continue
        header = f'{puzzle.puzzle_id} {puzzle.value_limit} {len(puzzle.starting_values)} {len(puzzle.targets)}\n'
        payload = header + ' '.join(map(str, puzzle.starting_values)) + '\n'
        payload += ' '.join(map(str, puzzle.targets)) + '\n'
        if mode in (6, 7, 8, 9):
            payload += str(len(best)) + '\n'
            payload += '\n'.join(' '.join(map(str, op)) for op in best) + '\n'
        info = {'config': config, 'before': len(best)}
        try:
            result = subprocess.run([str(ROOT/'build/dictionary_search'), *map(str,config)],
                                    input=payload, text=True, capture_output=True,
                                    check=True, timeout=timeout)
            identifier, encoded = result.stdout.strip().split(' ', 1)
            if identifier != puzzle.puzzle_id:
                raise ValueError('wrong puzzle identifier')
            candidate = json.loads(encoded)
            validate_program(puzzle, candidate)
            info['candidate'] = len(candidate)
            if len(candidate) < len(best):
                best = candidate
        except (subprocess.SubprocessError, ValueError, AssertionError) as error:
            info['failure'] = str(error)[:300]
        info['seconds'] = round(time.monotonic()-started,3)
        trials.append(info)
    return puzzle.puzzle_id, best, {'id': puzzle.puzzle_id, 'before': len(incumbent),
                                  'after': len(best), 'saved': len(incumbent)-len(best),
                                  'trials': trials}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('puzzles', 'current', 'output', 'report'):
        parser.add_argument('--'+flag, type=Path, required=True)
    parser.add_argument('--configs', default='[[3,0.18,52,56,20,0,0]]',
                        help='JSON array of native CLI argument arrays')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--start-index', type=int, default=0)
    parser.add_argument('--end-index', type=int)
    args = parser.parse_args()
    configs = json.loads(args.configs)
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
        report = {'optimizer': 'public_dictionary_portfolio', 'current': str(args.current),
                  'output': str(args.output), 'before': base['score'],
                  'after': sum(map(len,selected.values())), 'saved': sum(r['saved'] for r in rows),
                  'processed': len(rows), 'complete': complete, 'configs': configs,
                  'improved': sum(r['saved']>0 for r in rows),
                  'start_index': args.start_index, 'end_index': end,
                  'source': 'third_party/santa_dictionary/beam_search.cpp',
                  'source_sha256': hashlib.sha256((ROOT/'third_party/santa_dictionary/beam_search.cpp').read_bytes()).hexdigest(),
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
