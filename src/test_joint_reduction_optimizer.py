import random
import unittest
from joint_reduction_solver import build_graph, solve_job
from register_scheduler import register_peak, schedule_with_search, emit_cached
from recipe_graph_optimizer import close_graph, Recipe, InvalidGraph
from tiny_solver import Puzzle, validate_program
from validate_submission import replay


class JointReductionTests(unittest.TestCase):
    def check(self, p, program):
        validate_program(p, program)
        replay(p.puzzle_id, {'starting_values': p.starting_values, 'targets': set(p.targets),
                            'value_limit': p.value_limit, 'registers': p.registers}, program)

    def test_shared_square_and_neighbour(self):
        p = Puzzle('neighbours', (1, 10), (100, 101), 101, 4)
        graph = build_graph(p, .2, 0)
        program, peak = schedule_with_search(p, graph)
        self.check(p, program)
        self.assertEqual(len(program), 2)
        self.assertLessEqual(peak, p.registers)

    def test_subtraction_of_large_initial_values(self):
        p = Puzzle('initial-subtraction', (7, 13), (6, 42), 50, 4)
        graph = build_graph(p, .2, 0)
        program, _ = schedule_with_search(p, graph)
        self.check(p, program)
        self.assertEqual(len(program), 2)

    def test_neighbouring_power_does_not_create_a_cycle(self):
        p = Puzzle('cycle', (4, 22), (31, 32, 63, 127, 255), 300, 8)
        for metric in (0, 1):
            graph = build_graph(p, .1, metric)
            self.assertEqual(set(graph), set(close_graph(p.targets, set(p.starting_values), graph, {})))
            program, _ = schedule_with_search(p, graph)
            self.check(p, program)

    def test_empty_and_duplicate_initial_values(self):
        p = Puzzle('empty', (1, 2, 2), (1, 2), 10, 3)
        graph = build_graph(p, .2, 0)
        self.assertEqual(graph, {})
        self.assertEqual(register_peak(p, graph), 0)

    def test_random_targets_obey_bounds_and_exact_division(self):
        rng = random.Random(199995)
        for case in range(30):
            initial = tuple(rng.sample(range(1, 50), 4))
            limit = rng.randrange(100, 10000)
            targets = tuple(rng.sample(range(1, limit + 1), 8))
            p = Puzzle(str(case), initial, targets, limit, 48)
            for extended, factor_mode, pair_mode in ((False,0,False), (True,1,False), (False,2,True)):
                graph = build_graph(p, .2, 0, extended, factor_mode, pair_mode)
                program, _ = schedule_with_search(p, graph)
                self.check(p, program)

    def test_common_factor_is_built_once(self):
        base = 123456
        p = Puzzle('factor', (1, 2, 3, 5, 11), (3*base, 5*base, 11*base), 2000000, 48)
        graph = build_graph(p, .25, 0, factor_mode=1)
        self.assertIn(base, graph)
        for target in p.targets:
            self.assertEqual(graph[target].operator, '*')
            self.assertIn(base, graph[target].operands)
        program, _ = schedule_with_search(p, graph)
        self.check(p, program)

    def test_cache_recomputation_obeys_budget(self):
        p = Puzzle('cache', (1,), (7, 9, 12), 30, 3)
        recipes = {2: Recipe('+', 1, 1), 3: Recipe('+', 1, 2),
                   4: Recipe('+', 1, 3), 5: Recipe('+', 1, 4),
                   7: Recipe('+', 2, 5), 9: Recipe('+', 4, 5),
                   12: Recipe('+', 3, 9)}
        graph = close_graph(p.targets, {1}, recipes, {})
        program, peak = emit_cached(p, graph, 30)
        self.check(p, program)
        self.assertLessEqual(peak, 3)
        with self.assertRaises(InvalidGraph):
            emit_cached(p, graph, len(graph)-1)

    def test_keeps_short_incumbent(self):
        p = Puzzle('keep', (1, 2), (3,), 10, 2)
        incumbent = [['+', 0, 1, 0]]
        _, candidate, _ = solve_job((p, incumbent, (False, True)))
        self.assertEqual(candidate, incumbent)


if __name__ == '__main__':
    unittest.main()
