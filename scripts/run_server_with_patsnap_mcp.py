#!/usr/bin/env python3
"""Start the local server with an MCP key read from stdin, without persisting it."""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import create_server  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4180)
    args = parser.parse_args()
    key = sys.stdin.read().strip()
    if not key.startswith("sk-"):
        raise SystemExit("stdin does not contain a Patsnap key")
    os.environ["PATENT_PROVIDER"] = "patsnap_mcp_cn"
    os.environ["PATSNAP_MCP_API_KEY"] = key
    server = create_server(args.host, args.port)
    print("Research Delivery MCP regression server ready", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
