import unittest
from pathlib import Path
from tiny_solver import Puzzle,validate_program
from recipe_graph_optimizer import Recipe

AVAILABLE=(Path(__file__).resolve().parents[1]/'.deps/ortools/ortools').is_dir()


@unittest.skipUnless(AVAILABLE,'install optional OR-Tools dependencies')
class CPSATRecipeTests(unittest.TestCase):
    def test_selects_shared_recipe_graph(self):
        from cpsat_recipe_optimizer import optimize_cpsat
        p=Puzzle('shared',(7,11,13,17),(168,408),1000,7)
        original=[['*',0,1,4],['*',0,2,5],['+',4,5,6],
                  ['*',3,1,4],['*',3,2,5],['+',4,5,6]]
        candidate,info=optimize_cpsat(p,original,seconds=2)
        validate_program(p,candidate)
        self.assertEqual(len(candidate),3)
        self.assertEqual(info['saved'],3)

    def test_jointly_selects_two_new_helpers(self):
        from cpsat_recipe_optimizer import optimize_cpsat
        p=Puzzle('twohelpers',(7,11,13,17,19),(301,731),10000,10)
        original=[['*',0,1,5],['*',0,2,6],['+',5,6,7],['*',0,4,6],['+',7,6,8],
                  ['*',3,1,5],['*',3,2,6],['+',5,6,7],['*',3,4,6],['+',7,6,8]]
        extras={24:{Recipe('+',11,13)},43:{Recipe('+',24,19)},
                301:{Recipe('*',7,43)},731:{Recipe('*',17,43)}}
        candidate,info=optimize_cpsat(p,original,seconds=2,extra_catalog=extras)
        validate_program(p,candidate)
        self.assertEqual(len(candidate),4)
        self.assertEqual(info['saved'],6)


if __name__=='__main__':unittest.main()
