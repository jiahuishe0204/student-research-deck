#!/usr/bin/env python3
"""Build the browser-safe, file:// compatible delivery sample data bundle."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
payload = {
    "report": (ROOT / "docs" / "验证稿-慢性植入神经接口-调研报告.md").read_text(encoding="utf-8"),
    "slides": (ROOT / "docs" / "验证稿-慢性植入神经接口-PPT内容包.md").read_text(encoding="utf-8"),
}
serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
serialized = serialized.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
target = ROOT / "web" / "sample-delivery" / "data.js"
target.write_text(f"window.DELIVERY_SAMPLE={serialized};\n", encoding="utf-8")
print(target)
