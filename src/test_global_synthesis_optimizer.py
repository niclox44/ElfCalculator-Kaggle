import random
import unittest

from global_synthesis_optimizer import optimize_global
from tiny_solver import Puzzle, validate_program
from validate_submission import replay


class GlobalSynthesisTests(unittest.TestCase):
    def check(self, puzzle, program):
        validate_program(puzzle, program)
        replay(puzzle.puzzle_id, {'starting_values': puzzle.starting_values,
               'targets': set(puzzle.targets), 'value_limit': puzzle.value_limit,
               'registers': puzzle.registers}, program)

    def test_rewrites_two_outputs_with_one_new_shared_value(self):
        p = Puzzle('shared', (7, 11, 13, 17), (168, 408), 1000, 7)
        original = [['*', 0, 1, 4], ['*', 0, 2, 5], ['+', 4, 5, 6],
                    ['*', 3, 1, 4], ['*', 3, 2, 5], ['+', 4, 5, 6]]
        candidate, info = optimize_global(p, original)
        self.check(p, candidate)
        self.assertEqual(len(candidate), 3)
        self.assertEqual(info['global_saved'], 3)

    def test_preserves_overwritten_intermediate_target(self):
        p = Puzzle('transient', (7, 11, 13, 17), (77, 168, 408), 1000, 7)
        original = [['*', 0, 1, 4], ['*', 0, 2, 5], ['+', 4, 5, 6],
                    ['*', 3, 1, 4], ['*', 3, 2, 5], ['+', 4, 5, 6]]
        candidate, _ = optimize_global(p, original)
        self.check(p, candidate)
        self.assertLessEqual(len(candidate), len(original))

    def test_reuses_value_from_a_later_independent_branch(self):
        p = Puzzle('later', (7, 11, 13), (168, 24), 300, 6)
        original = [['*', 0, 1, 3], ['*', 0, 2, 4], ['+', 3, 4, 5], ['+', 1, 2, 3]]
        candidate, _ = optimize_global(p, original, cross_branch=True)
        self.check(p, candidate)
        self.assertEqual(len(candidate), 2)

    def test_expired_budget_preserves_program(self):
        p = Puzzle('budget', (7, 11, 13), (168,), 300, 6)
        original = [['*', 0, 1, 3], ['*', 0, 2, 4], ['+', 3, 4, 5]]
        candidate, _ = optimize_global(p, original, deadline=0)
        self.assertEqual(candidate, original)

    def test_initial_targets_and_empty_program(self):
        p = Puzzle('initial', (1, 2, 2), (1, 2), 10, 3)
        candidate, _ = optimize_global(p, [])
        self.assertEqual(candidate, [])

    def test_random_register_pressure_and_arithmetic_bounds(self):
        rng = random.Random(130000)
        for case in range(50):
            nregs = rng.randrange(2, 8)
            regs = [1, 2] + [None] * (nregs - 2)
            seen = {1, 2}
            program = []
            for _ in range(60):
                available = [i for i, v in enumerate(regs) if v is not None]
                a, b = rng.choice(available), rng.choice(available)
                x, y = regs[a], regs[b]
                op = rng.choice(('+', '-', '*', '/'))
                if op == '/' and x % y:
                    continue
                result = {'+': lambda: x+y, '-': lambda: x-y,
                          '*': lambda: x*y, '/': lambda: x//y}[op]()
                if not 0 < result <= 120:
                    continue
                dest = rng.randrange(nregs)
                program.append([op, a, b, dest])
                regs[dest] = result
                seen.add(result)
            p = Puzzle(str(case), (1, 2), tuple(rng.sample(sorted(seen), min(5, len(seen)))), 120, nregs)
            for cross_branch in (False, True):
                candidate, _ = optimize_global(p, program, rounds=2, proposal_limit=32,
                                               cross_branch=cross_branch)
                self.check(p, candidate)
                self.assertLessEqual(len(candidate), len(program))


if __name__ == '__main__':
    unittest.main()
