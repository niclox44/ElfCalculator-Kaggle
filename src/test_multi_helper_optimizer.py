import unittest
from multi_helper_optimizer import optimize_multi_helper
from tiny_solver import Puzzle,validate_program
from validate_submission import replay


class MultiHelperTests(unittest.TestCase):
    def test_two_new_operations_are_charged_and_reused(self):
        p=Puzzle('twohelpers',(7,11,13,17,19),(301,731),10000,10)
        original=[['*',0,1,5],['*',0,2,6],['+',5,6,7],['*',0,4,6],['+',7,6,8],
                  ['*',3,1,5],['*',3,2,6],['+',5,6,7],['*',3,4,6],['+',7,6,8]]
        validate_program(p,original)
        result,info=optimize_multi_helper(p,original)
        self.assertEqual(len(result),4)
        self.assertEqual(info['saved'],6)
        replay(p.puzzle_id,{'starting_values':p.starting_values,'targets':set(p.targets),
                           'value_limit':p.value_limit,'registers':p.registers},result)

    def test_initial_targets_preserved(self):
        p=Puzzle('initial',(1,2,2),(1,2),10,3)
        result,_=optimize_multi_helper(p,[])
        self.assertEqual(result,[])

    def test_transient_output_remains_required(self):
        p=Puzzle('transient',(7,11,13,17,19),(77,301,731),10000,10)
        original=[['*',0,1,5],['*',0,2,6],['+',5,6,7],['*',0,4,6],['+',7,6,8],
                  ['*',3,1,5],['*',3,2,6],['+',5,6,7],['*',3,4,6],['+',7,6,8]]
        result,_=optimize_multi_helper(p,original)
        validate_program(p,result)
        self.assertLessEqual(len(result),len(original))


if __name__=='__main__':unittest.main()
