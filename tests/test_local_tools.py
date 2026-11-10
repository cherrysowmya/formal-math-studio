import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from formal_math.local_tools import LeanVerifier, LeanExplore, _feedback, _masked, _named_theorems
from formal_math.mcp import Cancelled, ToolError


class LocalToolsTests(unittest.TestCase):
    def test_comment_and_string_mask_preserves_offsets(self):
        source = 'theorem t : True := by\n /- sorry /- axiom -/ -/\n trivial -- admit\n#check "sorry"\n'
        masked = _masked(source)
        self.assertEqual(len(masked), len(source))
        self.assertEqual(masked.count("\n"), source.count("\n"))
        self.assertNotIn("sorry", masked)
        self.assertNotIn("axiom", masked)

    def test_namespace_audit_names(self):
        code = 'namespace A\nsection x\n@[simp] theorem foo : True := by trivial\nend x\nend A\nlemma bar : True := by trivial\n'
        self.assertEqual(_named_theorems(code), ["A.foo", "bar"])

    def test_feedback_is_one_aggregate_budget(self):
        diagnostics, goal = _feedback("error1\nerror1\nerror2", "x : Nat\n⊢ x = x", 20)
        self.assertLessEqual(len(diagnostics) + len(goal), 20)
        self.assertEqual(goal, "x : Nat\n⊢ x = x")

    def test_oversized_goal_is_omitted_with_notice(self):
        diagnostics, goal = _feedback("error", "hypothesis\n" * 100, 100)
        self.assertEqual(goal, "")
        self.assertIn("Complete goal state omitted", diagnostics)
        self.assertLessEqual(len(diagnostics), 100)

    def test_proof_escape_rejected_before_compiler(self):
        checker = LeanVerifier({"lean": {"project_path": "/missing"}})
        result = checker.check("axiom falseProof : False\ntheorem t : False := falseProof", threading.Event())
        self.assertFalse(result["valid"])
        self.assertTrue(result["available"])

    def test_missing_tool_is_not_a_failed_mathematical_proof(self):
        result = LeanVerifier({"lean": {"project_path": "/missing"}}).check(
            "theorem t : True := by trivial", threading.Event())
        self.assertFalse(result["valid"])
        self.assertFalse(result["available"])

    def test_pre_cancelled_check_does_not_start_process(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(Cancelled):
            LeanVerifier({}).check("theorem t : True := by trivial", event)

    def _checker(self, directory, script, timeout=2):
        # Tiny injected compiler process exercises subprocess failure handling;
        # these unit fixtures are never used by the application runtime.
        return LeanVerifier({"lean": {"project_path": directory,
            "command": [sys.executable, "-c", script], "timeout_seconds": timeout}})

    def test_completed_compiler_without_axiom_audit_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._checker(directory, "print('done')").check(
                "theorem t : True := by trivial", threading.Event())
            self.assertFalse(result["valid"])
            self.assertIn("missing audit output", result["diagnostics"])
            self.assertEqual(list((Path(directory) / ".formal_math").iterdir()), [])

    def test_unapproved_axiom_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._checker(directory, 'print("\'t\' depends on axioms: [sorryAx]")').check(
                "theorem t : True := by trivial", threading.Event())
            self.assertFalse(result["valid"])
            self.assertIn("sorryAx", result["diagnostics"])

    def test_timeout_stops_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._checker(directory, "import time; time.sleep(10)", .1).check(
                "theorem t : True := by trivial", threading.Event())
            self.assertFalse(result["valid"])
            self.assertFalse(result["available"])
            self.assertIn("timed out", result["diagnostics"])

    def test_cancel_stops_running_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            event = threading.Event()
            timer = threading.Timer(.1, event.set)
            timer.start()
            try:
                with self.assertRaises(Cancelled):
                    self._checker(directory, "import time; time.sleep(10)").check(
                        "theorem t : True := by trivial", event)
            finally:
                timer.cancel()

    def test_source_limits_and_source_cache(self):
        calls = []
        class Client:
            def call(self, name, arguments, cancel):
                calls.append((name, arguments))
                if name == "search_summary":
                    return {"results": [{"id": index, "name": "Nat.test" + str(index)} for index in range(12)]}
                return {"source_text": "theorem test : True := by trivial"}
            def close(self):
                pass
        retriever = LeanExplore({"retrieval": {"limit": 12, "source_limit": 4}})
        retriever.client = Client()
        first = retriever.retrieve("query", threading.Event())
        second = retriever.retrieve("another query", threading.Event())
        self.assertEqual(len(first), 12)
        self.assertEqual(len(second), 12)
        self.assertEqual(sum(name == "get_source_code" for name, _ in calls), 4)
        self.assertEqual(sum(name == "search_summary" for name, _ in calls), 2)
        self.assertTrue(all(item["lean_source"] is None for item in first[4:]))

    def test_retrieval_unavailable_is_explicit(self):
        retriever = LeanExplore({"retrieval": {"command": ["/does/not/exist"]}})
        with self.assertRaises(ToolError):
            retriever.retrieve("query", threading.Event())
        retriever.close()


if __name__ == "__main__":
    unittest.main()
