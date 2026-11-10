import copy
import json
import os
import threading
import unittest
from unittest.mock import patch

from formal_math.config import defaults
from formal_math.providers import BudgetError, ModelGateway, ProviderError


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = defaults()
        self.events = []
        self.gateway = ModelGateway(self.config, lambda *event: self.events.append(event), threading.Event())
        self.messages = [{"role": "system", "content": "Prove the task"}, {"role": "user", "content": json.dumps({"task": "target", "goal": "goal", "current_candidate": "by rfl", "retrieved_declarations": [{"exact_name": "A"}, {"exact_name": "B"}]})}]

    def test_vllm_template_count_and_completion_use_same_thinking(self):
        calls = []
        def request(url, payload, headers, timeout):
            calls.append((url, copy.deepcopy(payload)))
            if url.endswith("/tokenize"):
                return {"count": 17}
            return {"choices": [{"message": {"content": "<think>private</think>```lean\nby rfl\n```"}, "finish_reason": "stop"}], "usage": {"completion_tokens": 25}}
        with patch("formal_math.providers._request", request):
            result = self.gateway.chat("formal_initial", self.messages)
        self.assertEqual(calls[0][0], "http://127.0.0.1:8081/tokenize")
        self.assertEqual(calls[0][1]["chat_template_kwargs"], calls[1][1]["chat_template_kwargs"])
        self.assertNotIn("private", result["text"])
        self.assertEqual(result["input_tokens"], 17)
        self.assertEqual(result["output_tokens"], 25)

    def test_packing_preserves_immutable_fields_and_whole_records(self):
        originals = copy.deepcopy(self.messages)
        self.config["roles"]["formal_initial"]["input_tokens"] = 100
        seen = []
        def request(url, payload, headers, timeout):
            if url.endswith("/tokenize"):
                packet = json.loads(payload["messages"][-1]["content"])
                seen.append(packet)
                return {"count": 200 if packet.get("retrieved_declarations") else 10}
            return {"choices": [{"message": {"content": "by rfl"}, "finish_reason": "stop"}]}
        with patch("formal_math.providers._request", request):
            self.gateway.chat("formal_initial", self.messages)
        self.assertEqual(self.messages, originals)
        self.assertEqual([len(p["retrieved_declarations"]) for p in seen], [2, 1, 0])
        self.assertTrue(all(p["task"] == "target" and p["goal"] == "goal" and p["current_candidate"] == "by rfl" for p in seen))

    def test_budget_fail_closed_before_generation(self):
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": '{"task":"required"}'}]
        with patch("formal_math.providers._request", return_value={"count": 9000}) as request:
            with self.assertRaises(BudgetError):
                self.gateway.chat("formal_initial", messages)
        self.assertEqual(request.call_count, 1)

    def test_missing_count_fails_before_generation(self):
        with patch("formal_math.providers._request", return_value={}) as request:
            with self.assertRaises(ProviderError):
                self.gateway.chat("formal_initial", self.messages)
        self.assertEqual(request.call_count, 1)

    def test_openai_responses_and_reasoning_token_usage(self):
        self.config["roles"]["formal_initial"].update(provider="openai", model="account-model")
        calls = []
        def request(url, payload, headers, timeout):
            calls.append((url, payload, headers))
            if url.endswith("input_tokens"):
                return {"input_tokens": 55}
            return {"status": "completed", "output": [{"type": "reasoning", "summary": []}, {"type": "message", "content": [{"type": "output_text", "text": "by rfl"}]}], "usage": {"output_tokens": 300}}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}), patch("formal_math.providers._request", request):
            result = self.gateway.chat("formal_initial", self.messages)
        self.assertTrue(calls[1][0].endswith("/responses"))
        self.assertFalse(calls[1][1]["store"])
        self.assertNotIn("temperature", calls[1][1])
        self.assertEqual(result["output_tokens"], 300)

    def test_claude_system_separation_and_thinking(self):
        self.config["roles"]["formal_initial"].update(provider="anthropic", model="account-claude")
        calls = []
        def request(url, payload, headers, timeout):
            calls.append(payload)
            if url.endswith("count_tokens"):
                return {"input_tokens": 75}
            return {"content": [{"type": "thinking", "thinking": "private"}, {"type": "text", "text": "by rfl"}], "stop_reason": "end_turn", "usage": {"output_tokens": 200}}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-secret"}), patch("formal_math.providers._request", request):
            result = self.gateway.chat("formal_initial", self.messages)
        self.assertEqual(calls[1]["system"], "Prove the task")
        self.assertEqual(calls[0]["thinking"], calls[1]["thinking"])
        self.assertEqual(calls[1]["temperature"], 1)
        self.assertLess(calls[1]["thinking"]["budget_tokens"], calls[1]["max_tokens"])
        self.assertEqual(result["text"], "by rfl")

    def test_claude_adaptive_mode_uses_same_config_for_count_and_generation(self):
        self.config["roles"]["formal_initial"].update(provider="anthropic", model="adaptive-claude")
        self.config["providers"]["anthropic"]["thinking_mode"] = "adaptive"
        calls = []
        def request(url, payload, headers, timeout):
            calls.append(payload)
            return {"input_tokens": 20} if url.endswith("count_tokens") else {"content": [{"type": "text", "text": "by rfl"}], "stop_reason": "end_turn"}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-secret"}), patch("formal_math.providers._request", request):
            self.gateway.chat("formal_initial", self.messages)
        self.assertEqual(calls[0]["thinking"], {"type": "adaptive"})
        self.assertEqual(calls[0]["thinking"], calls[1]["thinking"])
        self.assertNotIn("temperature", calls[1])

    def test_unfinished_thinking_has_no_public_answer(self):
        with patch("formal_math.providers._request", side_effect=[{"count": 1}, {"choices": [{"message": {"content": "<think>unfinished"}, "finish_reason": "length"}]}]):
            result = self.gateway.chat("formal_initial", self.messages)
        self.assertEqual(result["text"], "")
        self.assertEqual(result["finish_reason"], "length")


if __name__ == "__main__":
    unittest.main()
