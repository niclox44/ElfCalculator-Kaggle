"""Regression checks for numeric DAG rewriting and register scheduling."""

import unittest
import random

from recipe_graph_optimizer import (
    InvalidGraph, Recipe, cheapest_recipes, close_graph, extract_recipes,
    optimize, schedule, emit_with_recomputation, rewrite_available_values,
)
from tiny_solver import Puzzle, solve, validate_program
from validate_submission import replay


class RecipeGraphTests(unittest.TestCase):
    def check_program(self, puzzle, program):
        validate_program(puzzle, program)
        replay(puzzle.puzzle_id, {"starting_values": puzzle.starting_values,
               "targets": set(puzzle.targets), "value_limit": puzzle.value_limit,
               "registers": puzzle.registers}, program)

    def test_real_cross_source_improvement(self):
        # Source A builds 7 cheaply; source B supplies the shared recipe 11 = 7 + 4.
        puzzle = Puzzle("cross", (1, 2, 4, 5), (7, 11), 30, 8)
        first = [["+", 1, 3, 4], ["+", 3, 3, 5], ["+", 5, 0, 6]]
        second = [["+", 0, 1, 4], ["+", 4, 2, 5], ["+", 5, 2, 6]]
        best, metadata = optimize(puzzle, first, [second], rounds=4)
        self.check_program(puzzle, best)
        self.assertEqual(len(best), 2)
        self.assertGreater(metadata["accepted_moves"], 0)

    def test_cycles_rejected_even_if_arithmetic_is_valid(self):
        graph = {2: Recipe("-", 3, 1), 3: Recipe("+", 2, 1)}
        with self.assertRaises(InvalidGraph):
            close_graph((3,), {1}, graph, {})

    def test_missing_recipe_rejected(self):
        with self.assertRaises(InvalidGraph):
            close_graph((3,), {1}, {3: Recipe("+", 2, 1)}, {})

    def test_duplicate_operands_and_overwritten_targets(self):
        puzzle = Puzzle("transient", (1,), (2, 4, 8), 16, 1)
        graph = close_graph(puzzle.targets, {1}, {
            2: Recipe("+", 1, 1), 4: Recipe("*", 2, 2), 8: Recipe("+", 4, 4)}, {})
        program, peak = schedule(puzzle, graph)
        self.check_program(puzzle, program)
        self.assertEqual(len(program), 3)
        self.assertEqual(peak, 1)

    def test_exact_division_and_initial_target(self):
        puzzle = Puzzle("division", (3, 12, 3), (3, 4, 7), 20, 3)
        graph = close_graph(puzzle.targets, {3, 12}, {
            4: Recipe("/", 12, 3), 7: Recipe("+", 3, 4)}, {})
        program, _ = schedule(puzzle, graph)
        self.check_program(puzzle, program)
        self.assertEqual(len(program), 2)

    def test_identity_and_commutative_duplicates_are_removed(self):
        puzzle = Puzzle("identities", (1, 2), (3,), 8, 4)
        program = [["+", 0, 1, 2], ["+", 1, 0, 3], ["*", 2, 0, 2]]
        catalog, first = extract_recipes(puzzle, program)
        self.assertEqual(catalog, {3: {Recipe("+", 1, 2)}})
        self.assertEqual(first, {3: Recipe("+", 1, 2)})

    def test_register_failure_preserves_incumbent(self):
        puzzle = Puzzle("fallback", (1, 2), (3, 5, 6), 20, 2)
        program = [["+", 0, 1, 0], ["+", 0, 1, 0], ["/", 0, 0, 1], ["+", 0, 1, 0]]
        best, metadata = optimize(puzzle, program, [], rounds=2)
        self.check_program(puzzle, best)
        self.assertEqual(best, program)
        self.assertGreater(metadata["schedule_failures"], 0)

    def test_fallback_recipes_are_acyclic(self):
        catalog = {2: {Recipe("+", 1, 1), Recipe("-", 3, 1)},
                   3: {Recipe("+", 2, 1)}}
        chosen, costs = cheapest_recipes({1}, catalog)
        graph = close_graph((2, 3), {1}, chosen, {})
        self.assertEqual(len(graph), 2)
        self.assertEqual(costs[2], 1)

    def test_recomputation_obeys_budget_and_covers_targets(self):
        puzzle = Puzzle("recompute", (1,), (7, 9, 12), 30, 3)
        recipes = {2: Recipe("+", 1, 1), 3: Recipe("+", 1, 2),
                   4: Recipe("+", 1, 3), 5: Recipe("+", 1, 4),
                   7: Recipe("+", 2, 5), 9: Recipe("+", 4, 5),
                   12: Recipe("+", 3, 9)}
        graph = close_graph(puzzle.targets, {1}, recipes, {})
        program, peak = emit_with_recomputation(puzzle, graph, 30)
        self.check_program(puzzle, program)
        self.assertGreater(len(program), len(graph))
        self.assertLessEqual(peak, 3)
        with self.assertRaises(InvalidGraph):
            emit_with_recomputation(puzzle, graph, len(graph))

    def test_ssa_rewrite_keeps_transient_target_dependencies(self):
        program = [["+", 1, 3, 4], ["+", 3, 3, 5], ["+", 5, 0, 6]]
        for targets, expected in (((7, 11), 2), ((7, 10, 11), 3)):
            puzzle = Puzzle("coverage", (1, 2, 4, 5), targets, 30, 8)
            best, _ = rewrite_available_values(puzzle, program, {})
            self.check_program(puzzle, best)
            self.assertEqual(len(best), expected)

    def test_tiny_optima_preserved(self):
        for targets in ((3, 5, 7), (6, 9, 15), (7, 11, 13), (1,)):
            puzzle = Puzzle("tiny", (1, 2), targets, 16, 48)
            incumbent = solve(puzzle)
            best, _ = optimize(puzzle, incumbent, [], rounds=3)
            self.check_program(puzzle, best)
            self.assertEqual(len(best), len(incumbent))

    def test_random_valid_programs_never_regress(self):
        rng = random.Random(20261119)
        for case in range(40):
            count = rng.randrange(3, 9)
            registers = [1, 2] + [None] * (count - 2)
            seen = {1, 2}
            program = []
            for _ in range(200):
                available = [i for i, value in enumerate(registers) if value is not None]
                a, b = rng.choice(available), rng.choice(available)
                left, right = registers[a], registers[b]
                op = rng.choice(("+", "-", "*", "/"))
                if op == "/" and left % right:
                    continue
                result = {"+": lambda: left + right, "-": lambda: left - right,
                          "*": lambda: left * right, "/": lambda: left // right}[op]()
                if not 0 < result <= 64:
                    continue
                destination = rng.randrange(count)
                program.append([op, a, b, destination])
                registers[destination] = result
                seen.add(result)
                if len(program) >= 35:
                    break
            targets = tuple(rng.sample(sorted(seen), min(len(seen), 5)))
            puzzle = Puzzle(f"random_{case}", (1, 2), targets, 64, count)
            best, _ = optimize(puzzle, program, [], rounds=2, proposal_limit=24)
            self.check_program(puzzle, best)
            self.assertLessEqual(len(best), len(program))


if __name__ == "__main__":
    unittest.main()
