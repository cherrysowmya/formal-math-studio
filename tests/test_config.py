import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from formal_math.config import apply_overrides, load_config, public_config, validate


class ConfigurationTests(unittest.TestCase):
    def test_baseline_budgets_and_paths(self):
        config = load_config()
        self.assertEqual(config["roles"]["formal_initial"]["output_tokens"], 32000)
        self.assertEqual(config["roles"]["informal_reviewer"]["output_tokens"], 8192)
        self.assertEqual(config["retrieval"]["max_queries"], 7)
        self.assertTrue(Path(config["lean"]["project_path"]).is_absolute())
        self.assertEqual(set(config["providers"]), {"anthropic", "openai", "openrouter", "deepseek", "groq"})
        self.assertEqual({role["provider"] for role in config["roles"].values()}, {"anthropic"})

    def test_context_overflow_rejected(self):
        config = load_config()
        config["roles"]["formal_initial"]["input_tokens"] = 40000
        with self.assertRaisesRegex(ValueError, "input plus output"):
            validate(config)

    def test_browser_cannot_set_endpoint_or_command(self):
        config = load_config()
        with self.assertRaises(ValueError):
            apply_overrides(config, {"formal_initial": {"base_url": "http://elsewhere"}})
        with self.assertRaises(ValueError):
            apply_overrides(config, {"providers": {"openai": {"api_key": "secret"}}})
        with self.assertRaises(ValueError):
            apply_overrides(config, {"formal_initial": {"provider": "attacker"}})

    def test_role_override_does_not_mutate_config(self):
        config = load_config()
        updated = apply_overrides(config, {"formal_initial": {"provider": "openai", "model": "my-model"}})
        self.assertEqual(updated["roles"]["formal_initial"]["provider"], "openai")
        self.assertEqual(config["roles"]["formal_initial"]["provider"], "anthropic")

    def test_secrets_are_not_in_public_configuration(self):
        config = load_config()
        config["roles"]["discussion"]["accidental_secret"] = "hidden-value"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENAI_API_KEY": "sensitive-test-value"}):
            config["app"]["env_file"] = str(Path(tmp) / ".env")
            public = public_config(config)
        self.assertTrue(public["providers"]["openai"]["key_configured"])
        self.assertNotIn("sensitive-test-value", str(public))
        self.assertNotIn("hidden-value", str(public))

    def test_paths_resolve_relative_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "studio.toml"
            path.write_text('[lean]\nproject_path = "lean-project"\n')
            config = load_config(path)
            self.assertEqual(config["lean"]["project_path"], str((Path(tmp) / "lean-project").resolve()))

    def test_nonlocal_web_host_rejected(self):
        config = load_config()
        config["app"]["host"] = "0.0.0.0"
        with self.assertRaisesRegex(ValueError, "loopback"):
            validate(config)

    def test_invalid_api_key_variable_and_non_dotenv_path_are_rejected(self):
        config = load_config()
        config["providers"]["openai"]["api_key_env"] = "NOT A VARIABLE"
        with self.assertRaisesRegex(ValueError, "API-key environment variable"):
            validate(config)
        config = load_config()
        config["app"]["env_file"] = "not-dotenv.txt"
        with self.assertRaisesRegex(ValueError, "named .env"):
            validate(config)


if __name__ == "__main__":
    unittest.main()
