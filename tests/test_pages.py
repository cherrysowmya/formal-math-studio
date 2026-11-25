import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


class PagesTests(unittest.TestCase):
    def test_preview_packages_only_public_assets_and_never_loads_local_credentials(self):
        root = Path(__file__).resolve().parents[1]
        builder = runpy.run_path(str(root / "scripts/build-pages.py"))["build"]
        with tempfile.TemporaryDirectory() as tmp, patch("formal_math.credentials._read", side_effect=AssertionError("Must not read local credentials")):
            builder(tmp)
            output = Path(tmp)
            self.assertEqual({p.name for p in output.iterdir()}, {"index.html", "app.js", "styles.css", "preview-config.json", ".nojekyll"})
            html = (output / "index.html").read_text()
            self.assertIn('name="formal-math-mode" content="preview"', html)
            self.assertIn('href="./styles.css"', html)
            self.assertIn('src="./app.js"', html)
            config = json.loads((output / "preview-config.json").read_text())
            self.assertTrue(all(not p["key_configured"] and p["key_source"] is None for p in config["providers"].values()))
            self.assertNotIn("env_file", str(config))


if __name__ == "__main__":
    unittest.main()
