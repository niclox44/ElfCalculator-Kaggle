import random
import unittest

from recipe_graph_optimizer import Recipe, close_graph, select_executable_graph
from short_synthesis_optimizer import optimize_short, short_programs
from tiny_solver import Puzzle, validate_program
from validate_submission import replay


class SynthesisTests(unittest.TestCase):
    def check(self, puzzle, program):
        validate_program(puzzle, program)
        replay(puzzle.puzzle_id, {"starting_values": puzzle.starting_values,
               "targets": set(puzzle.targets), "value_limit": puzzle.value_limit,
               "registers": puzzle.registers}, program)

    def test_selects_larger_executable_graph(self):
        puzzle = Puzzle("selection", (1, 2), (5, 6), 20, 2)
        small = close_graph(puzzle.targets, {1, 2}, {
            3: Recipe("+", 1, 2), 5: Recipe("+", 2, 3), 6: Recipe("+", 1, 5)}, {})
        larger = close_graph(puzzle.targets, {1, 2}, {
            4: Recipe("+", 2, 2), 3: Recipe("-", 4, 1),
            6: Recipe("+", 3, 3), 5: Recipe("-", 6, 1)}, {})
        selected, failures = select_executable_graph(puzzle, [small, larger], 4)
        self.assertIsNotNone(selected)
        graph, program, _ = selected
        self.assertEqual(len(graph), 4)
        self.assertEqual(failures, 1)
        self.check(puzzle, program)

    def test_distributive_replacement_creates_new_intermediate(self):
        puzzle = Puzzle("factor", (7, 11, 13), (168,), 300, 6)
        original = [["*", 0, 1, 3], ["*", 0, 2, 4], ["+", 3, 4, 5]]
        result, info = optimize_short(puzzle, original)
        self.check(puzzle, result)
        self.assertEqual(len(result), 2)
        self.assertEqual(info["synthesis_new_intermediates"], 1)

    def test_does_not_lose_intermediate_target(self):
        puzzle = Puzzle("transient", (7, 11, 13), (77, 168), 300, 6)
        original = [["*", 0, 1, 3], ["*", 0, 2, 4], ["+", 3, 4, 5]]
        result, _ = optimize_short(puzzle, original)
        self.check(puzzle, result)
        self.assertEqual(len(result), 3)

    def test_legal_intermediates_and_exact_division(self):
        for target in range(1, 50):
            available = {3, 7, 11}
            for program in short_programs(target, available, 49):
                known = set(available)
                for op, a, b, result in program:
                    self.assertIn(a, known)
                    self.assertIn(b, known)
                    self.assertTrue(0 < result <= 49)
                    if op == "/":
                        self.assertEqual(a % b, 0)
                        self.assertEqual(result, a // b)
                    elif op == "-":
                        self.assertEqual(result, a - b)
                    elif op == "+":
                        self.assertEqual(result, a + b)
                    else:
                        self.assertEqual(result, a * b)
                    known.add(result)
                self.assertEqual(program[-1][-1], target)

    def test_three_step_branch_is_available(self):
        found = []
        for target in range(2, 150):
            candidates = list(short_programs(target, {3, 7, 11}, 200))
            found.extend(p for p in candidates if len(p) == 3)
        self.assertTrue(found)

    def test_three_step_chain_creates_two_intermediates(self):
        candidates = list(short_programs(38, {2, 3, 7}, 150))
        self.assertTrue(candidates)
        self.assertTrue(all(len(p) == 3 for p in candidates))
        self.assertTrue(any(p[-1][3] == 38 for p in candidates))

    def test_shared_producer_for_another_output_is_preserved(self):
        puzzle = Puzzle("shared", (7, 11, 13), (168, 84), 300, 7)
        original = [["*", 0, 1, 3], ["*", 0, 2, 4], ["+", 3, 4, 5], ["+", 3, 0, 6]]
        result, _ = optimize_short(puzzle, original)
        self.check(puzzle, result)
        self.assertLessEqual(len(result), len(original))

    def test_deadline_keeps_incumbent(self):
        puzzle = Puzzle("deadline", (7, 11, 13), (168,), 300, 6)
        original = [["*", 0, 1, 3], ["*", 0, 2, 4], ["+", 3, 4, 5]]
        result, info = optimize_short(puzzle, original, deadline=0)
        self.assertEqual(result, original)
        self.assertTrue(info["synthesis_budget_exhausted"])

    def test_random_programs_and_small_register_files(self):
        rng = random.Random(42)
        for case in range(80):
            count = rng.randrange(3, 9)
            registers = [1, 2] + [None] * (count - 2)
            seen = {1, 2}
            program = []
            for _ in range(100):
                available = [i for i, v in enumerate(registers) if v is not None]
                a, b = rng.choice(available), rng.choice(available)
                x, y = registers[a], registers[b]
                op = rng.choice(("+", "-", "*", "/"))
                if op == "/" and x % y:
                    continue
                result = {"+": lambda: x + y, "-": lambda: x - y,
                          "*": lambda: x * y, "/": lambda: x // y}[op]()
                if not 0 < result <= 100:
                    continue
                dest = rng.randrange(count)
                program.append([op, a, b, dest])
                registers[dest] = result
                seen.add(result)
            puzzle = Puzzle(str(case), (1, 2), tuple(rng.sample(sorted(seen), min(5, len(seen)))), 100, count)
            candidate, _ = optimize_short(puzzle, program, max_windows=20)
            self.check(puzzle, candidate)
            self.assertLessEqual(len(candidate), len(program))


if __name__ == "__main__":
    unittest.main()
