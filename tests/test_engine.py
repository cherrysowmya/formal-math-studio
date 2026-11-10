import json
import threading
import unittest

from formal_math.config import load_config
from formal_math.engine import solve
from formal_math.providers import ProviderError


TASK = 'theorem demo (n : Nat) : n = n := by\n  sorry\n'


class Verifier:
    def __init__(self, accept=True, available=True):
        self.accept = accept
        self.available = available
        self.calls = []

    def check(self, code, cancel):
        self.calls.append(code)
        return {'available': self.available, 'valid': self.accept and 'rfl' in code,
                'diagnostics': 'unsolved goals', 'goal': f'goal {len(self.calls)}'}


class Retriever:
    def __init__(self):
        self.queries = []

    def retrieve(self, query, cancel):
        self.queries.append(query)
        return [{'exact_name': 'Eq.refl', 'lean_source': 'Eq.refl (a : α) : a = a',
                 'description': 'reflexivity', 'data_version': 'local-test'}]


class Model:
    def __init__(self, success_at=1, verdict='PASS', incomplete=False):
        self.calls = []
        self.formals = 0
        self.success_at = success_at
        self.verdict = verdict
        self.incomplete = incomplete

    def __call__(self, role, messages):
        self.calls.append((role, messages))
        if role == 'informal_generator':
            text = json.dumps({'outline': 'Equality is reflexive.', 'queries': ['reflexivity of equality', 'equality identity']})
        elif role == 'informal_reviewer':
            text = json.dumps({'verdict': self.verdict, 'issues': [] if self.verdict == 'PASS' else ['A gap'], 'feedback': 'Check the argument'})
        elif role == 'discussion':
            text = json.dumps({'diagnosis': 'Need reflexivity', 'strategies': ['Use rfl'], 'intermediate_facts': []})
        else:
            self.formals += 1
            body = 'rfl' if self.formals >= self.success_at else f'exact missing_{self.formals}'
            text = f'```lean\nby\n  {body}\n```'
        return {'text': text, 'input_tokens': 20, 'output_tokens': 30,
                'finish_reason': 'length' if self.incomplete else 'stop'}


class EngineTests(unittest.TestCase):
    def run_engine(self, model, verifier=None, config=None, cancel=None):
        self.events = []
        self.retriever = Retriever()
        return solve(TASK, config or load_config(), model, verifier or Verifier(), self.retriever,
                     lambda *event: self.events.append(event), cancel or threading.Event())

    def test_verified_seed_bypasses_all_model_and_retrieval_calls(self):
        model, retriever = Model(), Retriever()
        outcome = solve(TASK.replace('sorry', 'rfl'), load_config(), model, Verifier(), retriever,
                        lambda *args: None, threading.Event())
        self.assertEqual(outcome['status'], 'verified')
        self.assertEqual(model.calls, [])
        self.assertEqual(retriever.queries, [])

    def test_initial_success_preserves_task(self):
        model = Model()
        result = self.run_engine(model)
        self.assertTrue(result['verified'])
        self.assertEqual([r for r, _ in model.calls], ['formal_initial'])
        self.assertEqual(result['usage']['formal_attempts'], 1)
        self.assertIn('theorem demo (n : Nat) : n = n :=', result['code'])

    def test_fresh_attempt_is_within_five_and_review_is_isolated(self):
        model = Model(success_at=3)
        result = self.run_engine(model)
        self.assertTrue(result['verified'])
        self.assertEqual([r for r, _ in model.calls], [
            'formal_initial', 'informal_generator', 'informal_reviewer',
            'formal_reviser', 'discussion', 'fresh_formal'])
        review_packet = json.loads(model.calls[2][1][1]['content'])
        self.assertIn('proposal', review_packet)
        self.assertNotIn('previous_outline', review_packet)
        fresh_packet = json.loads(model.calls[-1][1][1]['content'])
        self.assertNotIn('current_candidate', fresh_packet)

    def test_full_failure_limits_retrieval_and_attempts(self):
        model = Model(success_at=100)
        result = self.run_engine(model)
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['usage']['formal_attempts'], 5)
        self.assertEqual(result['usage']['task_queries'], 5)
        self.assertEqual(result['usage']['outline_queries'], 2)
        self.assertEqual(len(self.retriever.queries), 7)
        self.assertEqual([r for r, _ in model.calls].count('discussion'), 1)
        self.assertEqual([r for r, _ in model.calls].count('fresh_formal'), 1)

    def test_rejected_outline_does_not_issue_strategy_queries(self):
        result = self.run_engine(Model(success_at=2, verdict='REJECT'))
        self.assertEqual(result['usage']['outline_queries'], 0)

    def test_informal_refinement_is_bounded(self):
        model = Model(success_at=2, verdict='FAIL')
        result = self.run_engine(model)
        self.assertEqual([r for r, _ in model.calls].count('informal_generator'), 3)
        self.assertEqual([r for r, _ in model.calls].count('informal_reviewer'), 3)
        self.assertEqual(result['usage']['outline_queries'], 0)

    def test_incomplete_model_output_is_never_accepted(self):
        verifier = Verifier()
        result = self.run_engine(Model(incomplete=True), verifier)
        self.assertFalse(result['verified'])
        self.assertEqual(len(verifier.calls), 1)

    def test_unavailable_verifier_fails_without_generation(self):
        model = Model()
        result = self.run_engine(model, Verifier(available=False))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(model.calls, [])

    def test_cancellation_stops_before_tools(self):
        cancelled = threading.Event()
        cancelled.set()
        model = Model()
        result = self.run_engine(model, cancel=cancelled)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(model.calls, [])

    def test_task_mutation_is_rejected_before_lean(self):
        def mutator(role, messages):
            return {'text': '```lean\ntheorem changed : True := by trivial\n```',
                    'finish_reason': 'stop'}
        verifier = Verifier()
        result = self.run_engine(mutator, verifier)
        self.assertFalse(result['verified'])
        self.assertEqual(result['code'], TASK)
        self.assertEqual(len(verifier.calls), 1)

    def test_provider_outage_is_infrastructure_failure(self):
        def unavailable(role, messages):
            raise ProviderError('missing credentials')
        result = self.run_engine(unavailable)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('missing credentials', result['error'])
        self.assertEqual(result['usage']['formal_attempts'], 0)


if __name__ == '__main__':
    unittest.main()
