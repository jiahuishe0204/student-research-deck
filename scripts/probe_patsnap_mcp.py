#!/usr/bin/env python3
"""One-shot MCP probe; reads the key from stdin and never prints it."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patsnap_mcp import PatsnapMCPClient  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("tools", "search", "pipeline"))
    parser.add_argument("--query", default="CRISPR molecular diagnostics")
    args = parser.parse_args()
    key = sys.stdin.read().strip()
    if not key.startswith("sk-"):
        raise SystemExit("clipboard does not contain a Patsnap key")
    client = PatsnapMCPClient(key)
    if args.mode == "tools":
        tools = client.list_tools()
        print(json.dumps({"tool_count": len(tools), "tool_names": [item.get("name") for item in tools]}, ensure_ascii=False))
    elif args.mode == "search":
        records = client.search(args.query, 3)
        print(json.dumps({"record_count": len(records), "records": records}, ensure_ascii=False))
    else:
        from retrieval import search_all

        result = search_all(args.query, per_source=3, patent_client=client, include_patsnap=False)
        counts = {}
        for record in result["records"]:
            counts[record.get("source", "unknown")] = counts.get(record.get("source", "unknown"), 0) + 1
        print(json.dumps({
            "query": result["query"],
            "record_count": len(result["records"]),
            "source_counts": counts,
            "errors": result["errors"],
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
