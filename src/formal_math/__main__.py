from __future__ import annotations

import argparse
import json
from pathlib import Path
import threading

from .config import load_config


def main():
    parser = argparse.ArgumentParser(description="Local Lean agent workspace")
    parser.add_argument("--config", type=Path, help="Local TOML configuration")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the loopback-only web interface")
    serve.add_argument("--port", type=int, help="Override app.port from configuration")
    check = sub.add_parser("check", help="Check a Lean file locally, without model calls")
    check.add_argument("file", type=Path)
    sub.add_parser("print-config", help="Print public settings (never credentials)")
    args = parser.parse_args()
    config_path = args.config
    if config_path is None and Path("config/local.toml").is_file():
        config_path = Path("config/local.toml")
    config = load_config(config_path)
    if args.command == "print-config":
        from .config import public_config
        print(json.dumps(public_config(config), indent=2))
    elif args.command == "check":
        from .local_tools import LeanVerifier
        verifier = LeanVerifier(config)
        try:
            result = verifier.check(args.file.read_text(encoding="utf-8"), threading.Event())
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["valid"] else 1
        finally:
            verifier.close()
    else:
        from .web import create_server
        server = create_server(config, port=args.port or config["app"]["port"])
        print(f"Formal Math Studio: http://127.0.0.1:{server.server_port}")
        print("Files, Lean checking and orchestration stay on this computer. Ctrl-C stops the server.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            for run_id in list(server.run_store.runs):
                server.run_store.cancel(run_id)
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
