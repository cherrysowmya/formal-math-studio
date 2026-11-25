import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from formal_math.config import defaults
from formal_math.web import RunStore, create_server


class Tool:
    def close(self):
        pass


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config = defaults()
        config["app"]["output_dir"] = self.tmp.name
        config["app"]["env_file"] = str(Path(self.tmp.name) / ".env")
        def solver(code, config, chat, verifier, retriever, emit, cancel):
            emit("lean", "Compiler test adapter accepted the test fixture", "success")
            return {"code": code.replace("sorry", "rfl"), "verified": True, "status": "verified", "usage": {"model_calls": 0}}
        self.store = RunStore(config, solver, lambda _: (Tool(), Tool()))
        self.server = create_server(config, port=0, store=self.store)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, data=None, **headers):
        encoded = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=encoded, headers={"Content-Type": "application/json", **headers})
        return urllib.request.urlopen(req, timeout=5)

    def wait(self, run_id):
        for _ in range(100):
            with self.request("/api/runs/" + run_id) as response:
                result = json.load(response)
            if result["status"] in {"verified", "failed", "unverified", "cancelled"}:
                return result
            time.sleep(.02)
        self.fail("Local run did not finish")

    def test_run_persists_output_and_downloads_identical_bytes(self):
        code = "theorem unit_identity (n : Nat) : n = n := by sorry\n"
        with self.request("/api/runs", {"code": code, "filename": "../../proof.lean"}) as response:
            self.assertEqual(response.status, 202)
            run_id = json.load(response)["id"]
        result = self.wait(run_id)
        self.assertTrue(result["verified"])
        with self.request(result["download_url"]) as response:
            self.assertEqual(response.read().decode(), result["code"])
            self.assertEqual(response.headers["X-Proof-Verified"], "true")
        output = Path(self.tmp.name) / run_id / "proof_output.lean"
        self.assertEqual(output.read_text(), result["code"])
        self.assertTrue((output.parent / "input.lean").is_file())
        self.assertTrue((output.parent / "result.json").is_file())

    def test_cross_origin_run_creation_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/runs", {"code": "x"}, Origin="https://another-site.invalid")
        self.assertEqual(error.exception.code, 403)
        self.assertFalse(self.store.runs)

    def test_browser_saves_keys_and_gets_only_public_status(self):
        key = "sk-test-browser-value"
        with self.request("/api/credentials", {"api_keys": {"anthropic": key}}) as response:
            metadata = json.load(response)
        self.assertEqual(metadata["providers"]["anthropic"]["key_source"], ".env")
        self.assertNotIn(key, json.dumps(metadata))
        self.assertIn(key, (Path(self.tmp.name) / ".env").read_text())
        with self.request("/api/config") as response:
            self.assertNotIn(key, response.read().decode())
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/.env")
        self.assertEqual(error.exception.code, 404)
        with self.request("/api/credentials", {"api_keys": {"anthropic": None}}) as response:
            self.assertNotEqual(json.load(response)["providers"]["anthropic"]["key_source"], ".env")

    def test_add_custom_provider_persists_and_accepts_a_separate_key(self):
        data = {"name": "my_provider", "kind": "chat_completions", "base_url": "https://models.example/v1"}
        with self.request("/api/providers", data) as response:
            self.assertIn("my_provider", json.load(response)["providers"])
        with self.request("/api/credentials", {"api_keys": {"my_provider": "sk-custom-test"}}) as response:
            self.assertTrue(json.load(response)["providers"]["my_provider"]["key_configured"])
        saved = Path(self.tmp.name) / "providers.local.json"
        self.assertNotIn("sk-custom-test", saved.read_text())
        from formal_math.provider_settings import load_providers
        reloaded = defaults()
        reloaded["app"]["env_file"] = str(Path(self.tmp.name) / ".env")
        load_providers(reloaded)
        self.assertEqual(reloaded["providers"]["my_provider"]["api_key_env"], "CUSTOM_MY_PROVIDER_API_KEY")

    def test_custom_provider_cannot_replace_existing_or_embed_keys_in_url(self):
        for name, url in (("openai", "https://models.example/v1"),
                          ("unsafe", "https://models.example/v1?key=sk-private"),
                          ("unsafe", "http://models.example/v1")):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request("/api/providers", {"name": name, "kind": "chat_completions", "base_url": url})
            self.assertEqual(error.exception.code, 400)
            self.assertNotIn("sk-private", error.exception.read().decode())
            error.exception.close()
        self.assertFalse((Path(self.tmp.name) / "providers.local.json").exists())

    def test_cross_origin_credential_updates_and_noncredential_fields_are_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/credentials", {"api_keys": {"openai": "sk-private"}}, Origin="https://another-site.invalid")
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/credentials", {"api_keys": {"openai": "sk-private"}, "base_url": "http://elsewhere.invalid"})
        self.assertEqual(error.exception.code, 400)
        self.assertFalse((Path(self.tmp.name) / ".env").exists())

    def test_env_keys_are_redacted_from_errors_activity_and_saved_run_metadata(self):
        key = "sk-test-redaction-value"
        with self.request("/api/credentials", {"api_keys": {"anthropic": key}}):
            pass
        def failing(code, config, chat, verifier, retriever, emit, cancel):
            emit("system", "Unexpected key " + key, "error")
            raise RuntimeError("Adapter error with " + key)
        self.store.solver = failing
        with self.request("/api/runs", {"code": "theorem x : True := by trivial"}) as response:
            run_id = json.load(response)["id"]
        result = self.wait(run_id)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn(key, json.dumps(result))
        # Wait for the run record to be written after the in-memory status update.
        record = Path(self.tmp.name) / run_id / "result.json"
        for _ in range(100):
            if record.is_file():
                break
            time.sleep(.01)
        self.assertNotIn(key, record.read_text())

    def test_browser_cannot_override_endpoint_or_command(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/runs", {"code": "theorem x : True := by trivial", "role_overrides": {"formal_initial": {"base_url": "http://attacker.invalid"}}})
        self.assertEqual(error.exception.code, 400)

    def test_static_routes_and_path_traversal(self):
        for path in ("/", "/app.js", "/styles.css"):
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/../config/local.toml")
        self.assertEqual(error.exception.code, 404)

    def test_cancellation_never_promotes_late_verified_result(self):
        entered, finish = threading.Event(), threading.Event()
        def delayed(code, config, chat, verifier, retriever, emit, cancel):
            entered.set()
            finish.wait(3)
            return {"code": code, "verified": True, "status": "verified"}
        self.store.solver = delayed
        with self.request("/api/runs", {"code": "theorem x : True := by trivial"}) as response:
            run_id = json.load(response)["id"]
        self.assertTrue(entered.wait(1))
        with self.request(f"/api/runs/{run_id}/cancel", {}) as response:
            self.assertEqual(json.load(response)["status"], "cancelled")
        finish.set()
        for _ in range(100):
            if self.store.runs[run_id].get("path"):
                break
            time.sleep(.01)
        self.assertFalse(self.store.get(run_id)["verified"])
        self.assertEqual(self.store.get(run_id)["status"], "cancelled")

    def test_cancellation_during_output_write_is_not_overwritten(self):
        original = Path.write_text
        def cancel_during_write(path, *args, **kwargs):
            if path.name.endswith("_output.lean"):
                self.store.cancel(path.parent.name)
            return original(path, *args, **kwargs)
        with patch.object(Path, "write_text", cancel_during_write):
            with self.request("/api/runs", {"code": "theorem x : True := by trivial"}) as response:
                run_id = json.load(response)["id"]
            for _ in range(100):
                if self.store.runs[run_id].get("path"):
                    break
                time.sleep(.01)
            result = self.store.get(run_id)
            self.assertEqual(result["status"], "cancelled")
            self.assertFalse(result["verified"])
            self.assertTrue((Path(self.tmp.name) / run_id / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
