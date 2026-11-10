import unittest

from formal_math.proof import ProofSlot, ProofSlotError, extract_proof
from formal_math.packing import declarations, failures, feedback


TASK = 'import Mathlib\n\ntheorem example_target (n : Nat) : n = n := by\n  sorry\n'


class ProofTests(unittest.TestCase):
    def test_assembly_preserves_original_statement(self):
        slot = ProofSlot.from_source(TASK)
        code, _ = slot.assemble_response('by\n  rfl')
        self.assertTrue(code.startswith(slot.prefix))
        self.assertNotIn('sorry', code)
        self.assertIn('rfl', code)

    def test_mutated_header_and_extra_commands_rejected(self):
        slot = ProofSlot.from_source(TASK)
        with self.assertRaises(ValueError):
            slot.assemble_response('theorem example_target (n : Nat) : True := by trivial')
        with self.assertRaises(ValueError):
            slot.assemble('by\n rfl\nend\naxiom fake : False')

    def test_earlier_unfinished_theorem_rejected(self):
        with self.assertRaisesRegex(ProofSlotError, 'earlier declarations'):
            ProofSlot.from_source('theorem helper : True := by sorry\n' + TASK)

    def test_anonymous_example_rejected_before_generation(self):
        with self.assertRaisesRegex(ProofSlotError, 'named theorem'):
            ProofSlot.from_source('example : True := by sorry')

    def test_complete_helper_and_namespace_preserved(self):
        code = 'namespace Demo\ntheorem helper : True := by trivial\n' + TASK + 'end Demo\n'
        slot = ProofSlot.from_source(code)
        candidate = slot.assemble('by\n rfl')
        self.assertTrue(candidate.endswith('end Demo\n'))
        self.assertIn('theorem helper : True := by trivial', candidate)

    def test_reasoning_is_not_selected_as_proof(self):
        response = '<think>```lean\nby sorry\n```</think>\n```lean\nby\n rfl\n```'
        self.assertEqual(extract_proof(response), 'by\n rfl')
        with self.assertRaises(ProofSlotError):
            extract_proof('<think>unfinished')
        with self.assertRaises(ProofSlotError):
            extract_proof('```lean\nby rfl')

    def test_whole_declarations_packed_without_slicing(self):
        hits = [{"exact_name": "Huge", "lean_source": "x" * 10000},
                {"exact_name": "Useful", "lean_source": "theorem Useful : True := by trivial"}]
        packed = declarations(hits, 500)
        self.assertEqual([v['exact_name'] for v in packed], ['Useful'])
        self.assertEqual(packed[0]['lean_source'], hits[1]['lean_source'])

    def test_failure_memory_keeps_recent_pairs(self):
        records = [{'attempt': i, 'candidate': 'x', 'diagnostics': 'err'} for i in range(5)]
        self.assertEqual([r['attempt'] for r in failures(records)], [3, 4])

    def test_feedback_aggregate_cap_and_duplicates(self):
        packed = feedback({'goal': 'a goal', 'diagnostics': ['repeat', 'repeat', 'next']}, 20)
        self.assertLessEqual(len(packed['goal']) + len(packed['diagnostics']), 20)
        self.assertEqual(packed['diagnostics'].count('repeat'), 1)


if __name__ == '__main__':
    unittest.main()
