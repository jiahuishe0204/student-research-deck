"""Conservative EPO OPS client with quota and rate-limit protection."""

import base64
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

OPS_BASE = "https://ops.epo.org/3.2"
OFFICIAL_WEEKLY_FREE_BYTES = 4_000_000_000
DEFAULT_WEEKLY_WARNING_BYTES = 3_000_000_000
DEFAULT_WEEKLY_HARD_STOP_BYTES = OFFICIAL_WEEKLY_FREE_BYTES
DEFAULT_MIN_INTERVAL_SECONDS = 1.1
DEFAULT_RESPONSE_RESERVE_BYTES = 10_000_000


class EPOError(RuntimeError):
    pass


class EPOQuotaError(EPOError):
    pass


class SQLiteUsageStore:
    """Process-safe weekly usage meter backed by one shared SQLite file."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS epo_usage ("
                "week TEXT PRIMARY KEY, response_bytes INTEGER NOT NULL DEFAULT 0, "
                "requests INTEGER NOT NULL DEFAULT 0, server_weekly_bytes INTEGER NOT NULL DEFAULT 0, "
                "reserved_bytes INTEGER NOT NULL DEFAULT 0)"
            )

    def _connect(self):
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def snapshot(self, week):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_bytes, requests, server_weekly_bytes, reserved_bytes "
                "FROM epo_usage WHERE week=?", (week,),
            ).fetchone()
        values = row or (0, 0, 0, 0)
        return {"week": week, "response_bytes": values[0], "requests": values[1],
                "server_weekly_bytes": values[2], "reserved_bytes": values[3]}

    def reserve(self, week, amount, hard_stop):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT OR IGNORE INTO epo_usage(week) VALUES(?)", (week,))
            row = connection.execute(
                "SELECT response_bytes, server_weekly_bytes, reserved_bytes FROM epo_usage WHERE week=?",
                (week,),
            ).fetchone()
            measured = max(int(row[0]), int(row[1])) + int(row[2])
            if measured + amount > hard_stop:
                connection.rollback()
                return False
            connection.execute("UPDATE epo_usage SET reserved_bytes=reserved_bytes+? WHERE week=?", (amount, week))
        return True

    def record(self, week, reserved, response_size, server_weekly_bytes=None):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT OR IGNORE INTO epo_usage(week) VALUES(?)", (week,))
            if server_weekly_bytes is None:
                connection.execute(
                    "UPDATE epo_usage SET response_bytes=response_bytes+?, requests=requests+1, "
                    "reserved_bytes=MAX(0,reserved_bytes-?) WHERE week=?",
                    (response_size, reserved, week),
                )
            else:
                connection.execute(
                    "UPDATE epo_usage SET response_bytes=response_bytes+?, requests=requests+1, "
                    "server_weekly_bytes=MAX(server_weekly_bytes,?), reserved_bytes=MAX(0,reserved_bytes-?) WHERE week=?",
                    (response_size, server_weekly_bytes, reserved, week),
                )

    def release(self, week, reserved):
        with self._connect() as connection:
            connection.execute(
                "UPDATE epo_usage SET reserved_bytes=MAX(0,reserved_bytes-?) WHERE week=?", (reserved, week)
            )

    def replace(self, usage):
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO epo_usage(week,response_bytes,requests,server_weekly_bytes,reserved_bytes) "
                "VALUES(?,?,?,?,?)",
                (usage["week"], int(usage.get("response_bytes", 0)), int(usage.get("requests", 0)),
                 int(usage.get("server_weekly_bytes", 0)), int(usage.get("reserved_bytes", 0))),
            )


def _week_key(now=None):
    now = now or datetime.now(timezone.utc)
    iso = now.isocalendar()
    return "%04d-W%02d" % (iso.year, iso.week)


def _text(node):
    return "" if node is None else " ".join("".join(node.itertext()).split())


def _children_text(node, suffix):
    for child in node:
        if child.tag.endswith(suffix):
            return _text(child)
    return ""


class EPOClient:
    def __init__(self, consumer_key, consumer_secret, *, usage_path=None,
                 weekly_warning_bytes=DEFAULT_WEEKLY_WARNING_BYTES,
                 weekly_hard_stop_bytes=DEFAULT_WEEKLY_HARD_STOP_BYTES,
                 min_interval_seconds=DEFAULT_MIN_INTERVAL_SECONDS, opener=None):
        if not consumer_key or not consumer_secret:
            raise ValueError("EPO OPS credentials are required")
        if not 0 < weekly_warning_bytes < weekly_hard_stop_bytes <= OFFICIAL_WEEKLY_FREE_BYTES:
            raise ValueError("EPO quota thresholds must satisfy warning < hard stop <= official free quota")
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.usage_path = Path(usage_path) if usage_path else None
        self.usage_store = SQLiteUsageStore(self.usage_path) if self.usage_path else None
        self.weekly_warning_bytes = int(weekly_warning_bytes)
        self.weekly_hard_stop_bytes = int(weekly_hard_stop_bytes)
        self.min_interval_seconds = float(min_interval_seconds)
        available_margin = self.weekly_hard_stop_bytes - self.weekly_warning_bytes
        self.response_reserve_bytes = min(DEFAULT_RESPONSE_RESERVE_BYTES, max(1, available_margin // 10))
        self.opener = opener or urllib.request.urlopen
        self._token = ""
        self._token_expires_at = 0.0
        self._last_request_at = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls, usage_path=None):
        key = os.environ.get("EPO_OPS_CONSUMER_KEY", "").strip()
        secret = os.environ.get("EPO_OPS_CONSUMER_SECRET", "").strip()
        if not key or not secret:
            return None
        warning_gb = float(os.environ.get("EPO_OPS_WEEKLY_WARNING_GB", "3"))
        hard_stop_gb = float(os.environ.get("EPO_OPS_WEEKLY_HARD_STOP_GB", "4"))
        return cls(key, secret, usage_path=usage_path,
                   weekly_warning_bytes=int(warning_gb * 1_000_000_000),
                   weekly_hard_stop_bytes=int(hard_stop_gb * 1_000_000_000))

    def _usage(self):
        empty = {"week": _week_key(), "response_bytes": 0, "requests": 0, "server_weekly_bytes": 0}
        if not self.usage_store:
            return empty
        try:
            return self.usage_store.snapshot(empty["week"])
        except sqlite3.Error as exc:
            raise EPOQuotaError("EPO OPS 额度计量不可用，已安全停止请求") from exc

    def _save_usage(self, usage):
        if not self.usage_store:
            return
        self.usage_store.replace(usage)

    def _reserve_budget(self):
        if not self.usage_store:
            return
        try:
            allowed = self.usage_store.reserve(
                _week_key(), self.response_reserve_bytes, self.weekly_hard_stop_bytes
            )
        except sqlite3.Error as exc:
            raise EPOQuotaError("EPO OPS 额度计量不可用，已安全停止请求") from exc
        if not allowed:
            raise EPOQuotaError("EPO OPS 本周用量已进入 4 GB 临界保护区")

    def _record_usage(self, response_size, headers):
        server_value = headers.get("X-RegisteredQuotaPerWeek-Used")
        server_bytes = int(server_value) if server_value and str(server_value).isdigit() else None
        if self.usage_store:
            self.usage_store.record(
                _week_key(), self.response_reserve_bytes, int(response_size), server_bytes
            )

    def _throttle(self):
        delay = self.min_interval_seconds - (time.monotonic() - self._last_request_at)
        if delay > 0:
            time.sleep(delay)
        self._last_request_at = time.monotonic()

    def _access_token(self):
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        credentials = base64.b64encode((self.consumer_key + ":" + self.consumer_secret).encode()).decode()
        req = urllib.request.Request(
            OPS_BASE + "/auth/accesstoken", data=b"grant_type=client_credentials", method="POST",
            headers={"Authorization": "Basic " + credentials, "Content-Type": "application/x-www-form-urlencoded"},
        )
        with self.opener(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self._token = payload.get("access_token", "")
        if not self._token:
            raise EPOError("EPO OPS 未返回访问令牌")
        self._token_expires_at = time.time() + int(payload.get("expires_in", 1200))
        return self._token

    def _get(self, path, accept="application/ops+xml"):
        with self._lock:
            self._reserve_budget()
            self._throttle()
            try:
                req = urllib.request.Request(
                    OPS_BASE + "/rest-services" + path,
                    headers={"Authorization": "Bearer " + self._access_token(), "Accept": accept,
                             "User-Agent": "research-delivery-mvp/0.3"},
                )
                with self.opener(req, timeout=30) as response:
                    body = response.read()
                    headers = response.headers
                self._record_usage(len(body), headers)
                return body
            except urllib.error.HTTPError as exc:
                if self.usage_store:
                    self.usage_store.release(_week_key(), self.response_reserve_bytes)
                reason = exc.headers.get("X-Rejection-Reason", "") if exc.headers else ""
                if exc.code in (403, 429) and ("Quota" in reason or exc.code == 429):
                    raise EPOQuotaError("EPO OPS 拒绝请求：" + (reason or "rate limit")) from exc
                raise EPOError("EPO OPS HTTP %d" % exc.code) from exc
            except Exception:
                if self.usage_store:
                    self.usage_store.release(_week_key(), self.response_reserve_bytes)
                raise

    def search(self, query, limit=3):
        limit = max(1, min(int(limit), 3))
        cleaned = re.sub(r"[^A-Za-z0-9\-]+", " ", query).strip()[:300]
        operators = {"and", "or", "not"}
        terms = [term for term in cleaned.split() if len(term) >= 2 and term.lower() not in operators][:6]
        if not terms:
            raise ValueError("EPO OPS 检索需要英文关键词")
        cql = " and ".join("ta=%s" % term for term in terms)
        path = "/published-data/search?q=%s&Range=1-%d" % (urllib.parse.quote(cql, safe=""), limit)
        root = ET.fromstring(self._get(path))
        identifiers = []
        for node in root.iter():
            if not node.tag.endswith("document-id"):
                continue
            parts = (_children_text(node, "country"), _children_text(node, "doc-number"), _children_text(node, "kind"))
            identifier = ".".join(parts) if all(parts) else ""
            if identifier and identifier not in identifiers:
                identifiers.append(identifier)
        return [self.bibliography(identifier) for identifier in identifiers[:limit]]

    def bibliography(self, identifier):
        if not re.fullmatch(r"[A-Z]{2}\.[A-Z0-9]+\.[A-Z0-9]+", identifier):
            raise ValueError("EPO publication identifier is invalid")
        root = ET.fromstring(self._get(
            "/published-data/publication/docdb/%s/biblio" % identifier,
            accept="application/exchange+xml",
        ))
        titles = [node for node in root.iter() if node.tag.endswith("invention-title")]
        title = next((_text(node) for node in titles if node.attrib.get("lang") == "en"), "")
        title = title or (_text(titles[0]) if titles else identifier)
        abstracts = [_text(node) for node in root.iter() if node.tag.endswith("abstract")]
        return {
            "source": "EPO OPS", "source_id": "EPO:" + identifier, "patent_id": identifier,
            "pmid": "", "doi": "", "title": title, "abstract": abstracts[0] if abstracts else "",
            "authors": [], "journal": "", "year": "", "url": "https://worldwide.espacenet.com/patent/search?q=pn%3D" + identifier.replace(".", ""),
            "access": "patent_bibliographic_metadata",
        }

    def usage_snapshot(self):
        usage = self._usage()
        measured = max(int(usage.get("response_bytes", 0)), int(usage.get("server_weekly_bytes", 0)))
        usage.update({"warning_bytes": self.weekly_warning_bytes,
                      "warning_reached": measured >= self.weekly_warning_bytes,
                      "hard_stop_bytes": self.weekly_hard_stop_bytes,
                      "critical_reserve_bytes": self.response_reserve_bytes,
                      "official_free_bytes": OFFICIAL_WEEKLY_FREE_BYTES})
        return usage
