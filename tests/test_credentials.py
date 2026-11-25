import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from formal_math.config import defaults, load_config, public_config
from formal_math.credentials import api_keys, save_api_keys
from formal_math.providers import ModelGateway


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / ".env"
        self.config = defaults()
        self.config["app"]["env_file"] = str(self.path)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_saved_key_survives_reload_is_private_and_is_never_public(self):
        self.path.write_text('# My other settings\nUNRELATED=value\n')
        (self.root / ".gitignore").write_text('runtime/\n!.env\n')
        save_api_keys(self.config, {"anthropic": "sk-test-persisted"})
        self.assertIn('UNRELATED=value', self.path.read_text())
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertTrue((self.root / ".gitignore").read_text().endswith('.env\n.env.*\n!.env.example\n'))
        self.assertNotIn("ANTHROPIC_API_KEY", os.environ)
        config_path = self.root / "settings.toml"
        config_path.write_text('[app]\nenv_file = ".env"\n')
        reloaded = load_config(config_path)
        self.assertEqual(api_keys(reloaded)["anthropic"], ("sk-test-persisted", ".env"))
        metadata = public_config(reloaded)
        self.assertEqual(metadata["providers"]["anthropic"]["key_source"], ".env")
        self.assertNotIn("sk-test-persisted", json.dumps(metadata))

    def test_saved_keys_override_environment_without_changing_an_active_run(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-exported"
        self.assertEqual(api_keys(self.config)["anthropic"], ("sk-test-exported", "environment"))
        save_api_keys(self.config, {"anthropic": "sk-test-original"})
        gateway = ModelGateway(self.config, lambda *args: None, threading.Event())
        save_api_keys(self.config, {"anthropic": "sk-test-replacement"})
        self.assertEqual(gateway._connection("formal_initial")[3]["x-api-key"], "sk-test-original")
        self.assertEqual(gateway.redact("Failed with sk-test-original"), "Failed with [redacted]")
        self.assertEqual(api_keys(self.config)["anthropic"][0], "sk-test-replacement")
        save_api_keys(self.config, {"anthropic": None})
        self.assertEqual(api_keys(self.config)["anthropic"], ("sk-test-exported", "environment"))

    def test_dotenv_values_are_literal_data_and_unrelated_variables_are_not_loaded(self):
        value = 'sk-test-$(touch${IFS}should-not-exist)"\\'
        save_api_keys(self.config, {"openai": value})
        self.assertEqual(api_keys(self.config)["openai"][0], value)
        self.path.write_text("export OPENAI_API_KEY='sk-manual' # comment\n"
                             'ANTHROPIC_API_KEY="sk-quoted" # another comment\n'
                             'PYTHONPATH=$(arbitrary-command)\n')
        self.assertEqual(api_keys(self.config)["openai"][0], "sk-manual")
        self.assertEqual(api_keys(self.config)["anthropic"][0], "sk-quoted")
        self.assertNotIn("PYTHONPATH", os.environ)

    def test_invalid_updates_never_create_or_partially_modify_credentials(self):
        invalid = [[], {"unknown": "sk-private"}, {"openai": ""}, {"openai": "sk-private\nINJECTED=yes"},
                   {"openai": {"key": "sk-private"}}, {"openai": "sk-private", "anthropic": "a b"}]
        for updates in invalid:
            with self.subTest(updates=type(updates).__name__):
                with self.assertRaises(ValueError) as error:
                    save_api_keys(self.config, updates)
                self.assertNotIn("sk-private", str(error.exception))
                self.assertFalse(self.path.exists())

    def test_updates_remove_duplicate_assignments_and_preserve_other_settings(self):
        self.path.write_text('OPENAI_API_KEY="old"\n# Keep this\nOTHER=keep\nexport OPENAI_API_KEY=older\n')
        save_api_keys(self.config, {"openai": "sk-new", "anthropic": "sk-other"})
        self.assertEqual(self.path.read_text().count("OPENAI_API_KEY="), 1)
        self.assertIn("# Keep this\nOTHER=keep\n", self.path.read_text())
        save_api_keys(self.config, {"openai": None})
        self.assertNotIn("OPENAI_API_KEY", self.path.read_text())
        self.assertEqual(api_keys(self.config)["anthropic"][0], "sk-other")

    def test_symlinked_credential_files_are_rejected_without_writing_target(self):
        target = self.root / "other.env"
        target.write_text("untouched")
        self.path.symlink_to(target)
        config_path = self.root / "settings.toml"
        config_path.write_text('[app]\nenv_file = ".env"\n')
        with self.assertRaisesRegex(ValueError, "symbolic links"):
            save_api_keys(load_config(config_path), {"openai": "sk-new"})
        self.assertEqual(target.read_text(), "untouched")


if __name__ == "__main__":
    unittest.main()
