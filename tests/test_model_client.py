import json
import os
import http.client
import unittest
import urllib.error
from unittest.mock import patch

from model_client import ModelOutputTruncated, deepseek_json, parse_json_object, read_with_deadline


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, amount=None):
        if self.payload is None:
            return b""
        payload, self.payload = self.payload, None
        if isinstance(payload, bytes):
            return payload
        return json.dumps(payload).encode("utf-8")


class ModelClientTests(unittest.TestCase):
    def test_parse_json_object_repairs_safe_wrappers(self):
        self.assertEqual(parse_json_object('```json\n{"ok": true}\n```'), {"ok": True})
        self.assertEqual(parse_json_object('结果如下：\n{"ok": true}\n完成'), {"ok": True})

    def test_parse_json_object_rejects_truncated_content(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_json_object('{"ok": true')

    def test_response_reader_collects_chunks(self):
        class Chunked:
            fp = None
            def __init__(self): self.parts = [b'{"ok":', b'true}', b'']
            def read(self, amount=None): return self.parts.pop(0)
        self.assertEqual(read_with_deadline(Chunked(), 1), b'{"ok":true}')

    def test_response_reader_uses_remaining_total_deadline_for_reasoning_gaps(self):
        class Socket:
            timeout = None
            def settimeout(self, value): self.timeout = value
        class Raw:
            _sock = Socket()
        class FP:
            raw = Raw()
        class Response:
            fp = FP()
            def __init__(self): self.finished = False
            def read(self, amount=None):
                if self.finished: return b""
                self.finished = True
                return b"{}"
        response = Response()
        self.assertEqual(read_with_deadline(response, 300), b"{}")
        self.assertGreaterEqual(response.fp.raw._sock.timeout, 299.0)

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

    def test_remote_disconnect_is_recorded_and_retried(self):
        reply = FakeResponse({"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}})
        statuses = []
        with patch("model_client.urllib.request.urlopen", side_effect=[http.client.RemoteDisconnected(), reply]) as request:
            result, _ = deepseek_json(
                "key", "model", "system", "prompt", {},
                usage_callback=lambda attempt, status, usage, detail: statuses.append(status),
            )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(statuses, ["transport_error", "accepted"])
        self.assertEqual(request.call_count, 2)

    def test_length_truncation_is_recorded_without_repeating_same_paid_cap(self):
        reply = FakeResponse({"choices": [{"finish_reason": "length", "message": {"content": '{"unfinished":'}}],
                              "usage": {"prompt_tokens": 100, "completion_tokens": 4400, "total_tokens": 4500}})
        statuses = []
        with patch("model_client.urllib.request.urlopen", return_value=reply) as request:
            with self.assertRaises(ModelOutputTruncated):
                deepseek_json("key", "model", "system", "prompt", {}, max_tokens=4400, max_attempts=2,
                              usage_callback=lambda attempt, status, usage, detail: statuses.append(status))
        self.assertEqual(statuses, ["truncated"])
        self.assertEqual(request.call_count, 1)

    def test_http_error_keeps_provider_message_without_exposing_request(self):
        error = urllib.error.HTTPError(
            "https://api.example/chat/completions", 400, "Bad Request", {},
            __import__("io").BytesIO(json.dumps({"error": {"type": "invalid_request_error", "message": "model not found"}}).encode()),
        )
        details = []
        with patch("model_client.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "DeepSeek HTTP 400: type=invalid_request_error; message=model not found"):
                deepseek_json("secret-key", "model", "system", "prompt", {},
                              usage_callback=lambda attempt, status, usage, detail: details.append(detail))
        self.assertEqual(details, [{"status": 400, "provider_error": "type=invalid_request_error; message=model not found"}])


if __name__ == "__main__":
    unittest.main()
