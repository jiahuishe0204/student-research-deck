import json
import os
import unittest
from unittest.mock import patch

from model_client import deepseek_json, parse_json_object


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ModelClientTests(unittest.TestCase):
    def test_parse_json_object_repairs_safe_wrappers(self):
        self.assertEqual(parse_json_object('```json\n{"ok": true}\n```'), {"ok": True})
        self.assertEqual(parse_json_object('结果如下：\n{"ok": true}\n完成'), {"ok": True})

    def test_parse_json_object_rejects_truncated_content(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_json_object('{"ok": true')
    def test_validation_failure_retries_and_accumulates_usage(self):
        replies = [
            FakeResponse({"choices": [{"message": {"content": '{"ok": false}'}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}),
            FakeResponse({"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}}),
        ]

        def validate(value):
            if not value["ok"]:
                raise ValueError("未通过")
            return value

        with patch("model_client.urllib.request.urlopen", side_effect=replies) as request:
            result, usage = deepseek_json("key", "model", "system", "prompt", {}, validator=validate)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(usage, {"prompt_tokens": 21, "completion_tokens": 5, "total_tokens": 26, "attempts": 2})
        self.assertEqual(request.call_count, 2)

    def test_compatible_base_url_is_used(self):
        reply = FakeResponse({"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}})
        with patch.dict(os.environ, {"DEEPSEEK_BASE_URL": "https://gateway.example/v1/"}), patch("model_client.urllib.request.urlopen", return_value=reply) as request:
            deepseek_json("key", "model", "system", "prompt", {})

        self.assertEqual(request.call_args.args[0].full_url, "https://gateway.example/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
