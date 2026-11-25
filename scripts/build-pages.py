#!/usr/bin/env python3
"""Build a static interface preview without reading local settings or secrets."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from formal_math.config import defaults


def build(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    static = ROOT / "src/formal_math/static"
    html = (static / "index.html").read_text()
    html = html.replace('<head>', '<head>\n  <meta name="formal-math-mode" content="preview">', 1)
    (destination / "index.html").write_text(html)
    for name in ("app.js", "styles.css"):
        shutil.copyfile(static / name, destination / name)
    config = defaults()
    public = {
        "roles": config["roles"], "limits": config["limits"],
        "providers": {name: {"kind": provider["kind"], "base_url": provider["base_url"],
                              "key_configured": False, "key_source": None, "key_editable": True}
                      for name, provider in config["providers"].items()},
    }
    (destination / "preview-config.json").write_text(json.dumps(public, indent=2) + "\n")
    (destination / ".nojekyll").touch()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    build(parser.parse_args().output)
