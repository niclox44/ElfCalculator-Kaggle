import unittest
from lns_optimizer import solve_job,ROOT
from tiny_solver import Puzzle,validate_program
from validate_submission import replay


@unittest.skipUnless((ROOT/'build/elfopt_extended').is_file(),'compile the optional native optimizer')
class RebaseTests(unittest.TestCase):
    def test_replaces_shared_hub_and_both_branches_atomically(self):
        p=Puzzle('rebase',(7,11,13,5,18),(865,1019),100000,10)
        original=[['*',0,1,5],['/',0,0,6],['+',5,6,7],['*',7,1,8],
                  ['+',8,0,8],['*',7,2,8],['+',8,3,8]]
        validate_program(p,original)
        _,program,info=solve_job((p,original,[['--time',2,'--rebase',1,'--seed',1]],10))
        self.assertEqual(len(program),5)
        self.assertEqual(info['saved'],2)
        replay(p.puzzle_id,{'starting_values':p.starting_values,'targets':set(p.targets),
                           'value_limit':p.value_limit,'registers':p.registers},program)

    def test_keeps_shared_hub_if_it_is_an_output(self):
        p=Puzzle('requiredhub',(7,11,13,5,18),(78,865,1019),100000,10)
        original=[['*',0,1,5],['/',0,0,6],['+',5,6,7],['*',7,1,8],
                  ['+',8,0,8],['*',7,2,8],['+',8,3,8]]
        _,program,_=solve_job((p,original,[['--time',2,'--rebase',1]],10))
        validate_program(p,program)
        self.assertLessEqual(len(program),len(original))


if __name__=='__main__':unittest.main()
