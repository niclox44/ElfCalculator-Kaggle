import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class RecipeSelectionTests(unittest.TestCase):
    def test_rejects_circular_derivations(self):
        payload='3 4 1 2 2000\n0\n0 1 -1\n1 0 -1\n0 2 -1\n2 -1 -1\n'
        tested=0
        for name in ('select_recipes_lazy','select_recipes_bv'):
            binary=ROOT/'build'/name
            if not binary.exists():continue
            tested+=1
            result=subprocess.run([str(binary)],input=payload,text=True,capture_output=True,
                                  timeout=10,check=True)
            lines=result.stdout.splitlines()
            self.assertEqual(lines[0],'sat 2')
            self.assertEqual(set(map(int,lines[1].split())),{2,3})
        if not tested:self.skipTest('compile an optional native recipe selector')


if __name__=='__main__':unittest.main()
