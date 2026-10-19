"""PostgreSQL repository implementing atomic delivery state transitions."""

from __future__ import annotations

from datetime import datetime, timezone
import hmac
import json
import uuid


def _one(cursor):
    row = cursor.fetchone()
    return row[0] if row else None


class PostgresDeliveryRepository:
    def __init__(self, connection, public_origin):
        self.connection = connection
        self.public_origin = public_origin.rstrip("/")

    def encrypted_email_for_user(self, user_id):
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT email_ciphertext,email_key_version
                 FROM users WHERE user_id=%s""", (str(user_id),))
        row = cursor.fetchone()
        return {"email_ciphertext": bytes(row[0]), "email_key_version": row[1]} if row else None

    def encrypted_challenge(self, challenge_id):
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT email_ciphertext,code_ciphertext FROM email_challenges
                 WHERE challenge_id=%s AND consumed_at IS NULL AND expires_at>CURRENT_TIMESTAMP""",
            (str(challenge_id),),
        )
        row = cursor.fetchone()
        return {"email_ciphertext": bytes(row[0]), "code_ciphertext": bytes(row[1])} if row else None

    def create_otp_challenge_and_event(self, **values):
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (values["email_hash"],))
            cursor.execute(
                """SELECT issued_at FROM email_challenges WHERE email_hash=%s
                     AND consumed_at IS NULL ORDER BY issued_at DESC LIMIT 1 FOR UPDATE""",
                (values["email_hash"],),
            )
            previous = cursor.fetchone()
            if previous and (values["issued_at"] - previous[0]).total_seconds() < 60:
                raise ValueError("请在 60 秒后重发验证码")
            cursor.execute("""UPDATE email_challenges SET consumed_at=%s,code_ciphertext=NULL
                               WHERE email_hash=%s AND consumed_at IS NULL""",
                           (values["issued_at"], values["email_hash"]))
            cursor.execute(
                """INSERT INTO email_challenges
                       (challenge_id,email_hash,email_ciphertext,code_hash,code_ciphertext,
                        email_key_version,issued_at,expires_at)
                     VALUES (%s,%s,%s,%s,%s,1,%s,%s)""",
                (values["challenge_id"], values["email_hash"], values["email_ciphertext"],
                 values["code_hash"], values["code_ciphertext"], values["issued_at"], values["expires_at"]),
            )
            cursor.execute(
                """INSERT INTO delivery_events
                       (event_id,idempotency_key,event_type,status,payload)
                     VALUES (%s,%s,'send_otp','pending',%s::jsonb)""",
                (values["event_id"], values["idempotency_key"],
                 json.dumps({"challenge_id": values["challenge_id"], "minutes": "10"},
                            separators=(",", ":"))),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def user_id_for_email_hash(self, email_hash):
        cursor = self.connection.cursor()
        cursor.execute("SELECT user_id FROM users WHERE email_hash=%s", (email_hash,))
        row = cursor.fetchone()
        return str(row[0]) if row else None

    def verify_challenge_and_open_session(self, **values):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """SELECT code_hash,attempts,expires_at,consumed_at FROM email_challenges
                     WHERE challenge_id=%s FOR UPDATE""", (values["challenge_id"],))
            row = cursor.fetchone()
            valid = bool(row and row[3] is None and row[2] > values["now"]
                         and row[1] < 5 and hmac.compare_digest(row[0], values["submitted_hash"]))
            if not valid:
                if row and row[3] is None:
                    cursor.execute("""UPDATE email_challenges SET attempts=LEAST(5,attempts+1),
                                       consumed_at=CASE WHEN attempts+1>=5 THEN %s ELSE consumed_at END,
                                       code_ciphertext=CASE WHEN attempts+1>=5 THEN NULL ELSE code_ciphertext END
                                       WHERE challenge_id=%s""", (values["now"], values["challenge_id"]))
                self.connection.commit()
                return False
            cursor.execute("""UPDATE email_challenges SET consumed_at=%s,code_ciphertext=NULL
                               WHERE challenge_id=%s""", (values["now"], values["challenge_id"]))
            cursor.execute(
                """INSERT INTO users(user_id,email_hash,email_ciphertext,email_key_version,verified_at)
                     VALUES (%s,%s,%s,1,%s) ON CONFLICT(email_hash) DO UPDATE SET verified_at=EXCLUDED.verified_at
                     RETURNING user_id""",
                (values["user_id"], values["email_hash"], values["user_email_ciphertext"], values["now"]),
            )
            actual_user_id = str(cursor.fetchone()[0])
            cursor.execute(
                """INSERT INTO user_sessions
                       (session_hash,user_id,csrf_hash,created_at,last_active_at,expires_at)
                     VALUES (%s,%s,%s,%s,%s,%s)""",
                (values["session_hash"], actual_user_id, values["csrf_hash"], values["now"],
                 values["now"], values["session_expires_at"]),
            )
            self.connection.commit()
            return actual_user_id
        except Exception:
            self.connection.rollback()
            raise

    def prepare_artifact(self, *, task_id, artifact_id, kind, object_key, content_type):
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO task_artifacts
                (artifact_id,task_id,kind,object_key,sha256,size_bytes,content_type,status,expires_at)
            SELECT %s,%s,%s,%s,%s,1,%s,'prepared',CURRENT_TIMESTAMP + INTERVAL '7 days'
             WHERE EXISTS (SELECT 1 FROM research_tasks WHERE task_id=%s AND status IN ('running','completed'))
            ON CONFLICT (artifact_id) DO NOTHING
            """,
            (str(artifact_id), task_id, kind, object_key, "0" * 64, content_type, task_id),
        )
        cursor.execute(
            """SELECT jsonb_build_object('artifact_id',artifact_id,'status',status,
                       'object_key',object_key) FROM task_artifacts
                 WHERE artifact_id=%s AND task_id=%s AND object_key=%s FOR UPDATE""",
            (str(artifact_id), task_id, object_key),
        )
        result = _one(cursor)
        if not result:
            self.connection.rollback()
            raise ValueError("任务不存在或产物标识冲突")
        self.connection.commit()
        return result

    def publish_artifact_and_complete(self, **values):
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT user_id,status FROM research_tasks WHERE task_id=%s FOR UPDATE", (values["task_id"],))
            owner = cursor.fetchone()
            if not owner:
                raise ValueError("任务不存在")
            user_id, task_status = owner
            if task_status not in ("running", "completed"):
                raise RuntimeError("任务已取消或失败，拒绝发布")
            cursor.execute(
                """
                UPDATE task_artifacts SET sha256=%s,size_bytes=%s,content_type=%s,etag=%s,
                    status=CASE WHEN status='published' THEN status ELSE 'uploaded' END
                 WHERE artifact_id=%s AND task_id=%s AND object_key=%s
                   AND status IN ('prepared','uploaded','published')
                RETURNING artifact_id
                """,
                (values["sha256"], values["size_bytes"], values["content_type"], values["etag"],
                 str(values["artifact_id"]), values["task_id"], values["object_key"]),
            )
            if not cursor.fetchone():
                raise RuntimeError("产物发布状态冲突")
            cursor.execute(
                """SELECT COUNT(DISTINCT kind) FROM task_artifacts
                     WHERE task_id=%s AND kind IN ('report','ppt_content','references')
                       AND status IN ('uploaded','published')""", (values["task_id"],))
            ready = int(cursor.fetchone()[0]) == 3
            if not ready:
                self.connection.commit()
                return {"status": "uploaded", **values}
            if task_status == "completed":
                self.connection.commit()
                return {"status": "published", **values}
            cursor.execute(
                """UPDATE task_artifacts SET status='published',downloadable=TRUE,published_at=%s,
                           expires_at=%s,remind_at=%s
                     WHERE task_id=%s AND kind IN ('report','ppt_content','references')
                       AND status IN ('uploaded','published')""",
                (values["published_at"], values["expires_at"], values["remind_at"], values["task_id"]),
            )
            cursor.execute("""UPDATE research_tasks SET status='completed',updated_at=%s
                               WHERE task_id=%s AND status='running'""",
                           (values["published_at"], values["task_id"]))
            cursor.execute(
                """UPDATE free_entitlements SET state='consumed',task_id=NULL,updated_at=%s
                     WHERE user_id=%s AND state='reserved' AND task_id=%s""",
                (values["published_at"], str(user_id), values["task_id"]),
            )
            task_url = "%s/tasks/%s" % (self.public_origin, values["task_id"])
            cursor.execute(
                """INSERT INTO delivery_events
                       (event_id,idempotency_key,task_id,user_id,event_type,status,payload)
                     VALUES (%s,%s,%s,%s,'send_completed','pending',%s::jsonb)
                     ON CONFLICT (idempotency_key) DO NOTHING""",
                (str(uuid.uuid4()), values["completion_idempotency_key"], values["task_id"],
                 str(user_id), json.dumps({"task_label": "调研任务", "site_url": task_url},
                                          ensure_ascii=False, separators=(",", ":"))),
            )
            cursor.execute(
                """INSERT INTO delivery_events
                       (event_id,idempotency_key,task_id,user_id,event_type,status,available_at,payload)
                     VALUES (%s,%s,%s,%s,'send_expiry','pending',%s,%s::jsonb)
                     ON CONFLICT (idempotency_key) DO NOTHING""",
                (str(uuid.uuid4()), values["reminder_idempotency_key"], values["task_id"],
                 str(user_id), values["remind_at"],
                 json.dumps({"task_label": "调研任务", "site_url": task_url,
                             "expiry_date": values["expires_at"].date().isoformat()},
                            ensure_ascii=False, separators=(",", ":"))),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return {"status": "published", **values}

    def authorized_artifact(self, *, user_id, task_id, artifact_id, now):
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT jsonb_build_object('artifact_id',a.artifact_id,'object_key',a.object_key,
                       'status',a.status,'downloadable',a.downloadable,'expires_at',a.expires_at)
              FROM task_artifacts a JOIN research_tasks t ON t.task_id=a.task_id
             WHERE t.user_id=%s AND t.task_id=%s AND a.artifact_id=%s
               AND a.status='published' AND a.downloadable=TRUE AND a.expires_at>%s
            """, (str(user_id), task_id, str(artifact_id), now))
        return _one(cursor)

    def enqueue_due_expiry_reminders(self, *, now, limit):
        # Reminder rows are scheduled atomically during publish. This query only
        # returns due, still-pending rows for observability; it creates nothing.
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT DISTINCT e.event_id FROM delivery_events e
                   JOIN task_artifacts a ON a.task_id=e.task_id
                 WHERE e.event_type='send_expiry' AND e.available_at<=%s
                   AND e.status IN ('pending','running') AND a.expires_at>%s
                 ORDER BY e.event_id LIMIT %s""", (now, now, int(limit)))
        return [row[0] for row in cursor.fetchall()]

    def purge_expired_challenge_secrets(self, *, now):
        cursor = self.connection.cursor()
        cursor.execute("""UPDATE email_challenges SET email_ciphertext=NULL,code_ciphertext=NULL
                           WHERE expires_at<=%s AND (email_ciphertext IS NOT NULL OR code_ciphertext IS NOT NULL)
                           RETURNING challenge_id""", (now,))
        cleared = len(cursor.fetchall())
        cursor.execute("DELETE FROM email_challenges WHERE expires_at<%s-INTERVAL '30 days'", (now,))
        self.connection.commit()
        return cleared

    def claim_due_expirations(self, *, now, limit):
        cursor = self.connection.cursor()
        token = str(uuid.uuid4())
        cursor.execute(
            """UPDATE task_artifacts SET status='delete_pending',downloadable=FALSE,
                       delete_lease_token=%s,delete_lease_until=%s+INTERVAL '2 minutes'
                 WHERE artifact_id IN (
                     SELECT artifact_id FROM task_artifacts
                      WHERE expires_at<=%s AND status IN ('published','delete_pending')
                        AND (delete_next_attempt_at IS NULL OR delete_next_attempt_at<=%s)
                        AND (delete_lease_until IS NULL OR delete_lease_until<%s)
                        AND delete_attempts<8
                      ORDER BY expires_at FOR UPDATE SKIP LOCKED LIMIT %s)
                RETURNING artifact_id,delete_lease_token""",
            (token, now, now, now, now, int(limit)))
        rows = [{"artifact_id": row[0], "lease_token": str(row[1])} for row in cursor.fetchall()]
        self.connection.commit()
        return rows

    def mark_delete_pending(self, artifact_id, now, lease_token=None):
        cursor = self.connection.cursor()
        cursor.execute(
            """UPDATE task_artifacts SET status='delete_pending',downloadable=FALSE
                 WHERE artifact_id=%s AND status IN ('published','delete_pending')
                   AND (%s IS NULL OR delete_lease_token=%s)
                RETURNING jsonb_build_object('status',status,'object_key',object_key)""",
            (str(artifact_id), lease_token, lease_token),
        )
        result = _one(cursor)
        if lease_token is not None and not result:
            self.connection.rollback()
            return None
        if not result:
            cursor.execute("SELECT jsonb_build_object('status',status,'object_key',object_key) FROM task_artifacts WHERE artifact_id=%s", (str(artifact_id),))
            result = _one(cursor)
        self.connection.commit()
        return result

    def record_delete_failure(self, artifact_id, error_code, lease_token=None):
        cursor = self.connection.cursor()
        cursor.execute("""UPDATE task_artifacts SET delete_attempts=delete_attempts+1,last_delete_error=%s,
                           delete_next_attempt_at=CURRENT_TIMESTAMP + LEAST(3600,15*POWER(2,delete_attempts)) * INTERVAL '1 second',
                           delete_lease_token=NULL,delete_lease_until=NULL
                           WHERE artifact_id=%s AND (%s IS NULL OR delete_lease_token=%s)
                           RETURNING artifact_id""",
                       (str(error_code)[:80], str(artifact_id), lease_token, lease_token))
        if lease_token is not None and not cursor.fetchone():
            self.connection.rollback()
            raise RuntimeError("删除租约已失效")
        self.connection.commit()

    def mark_deleted(self, artifact_id, now, lease_token=None):
        cursor = self.connection.cursor()
        cursor.execute("""UPDATE task_artifacts SET status='deleted',downloadable=FALSE,deleted_at=%s,
                           last_delete_error=NULL,delete_lease_token=NULL,delete_lease_until=NULL
                           WHERE artifact_id=%s AND (%s IS NULL OR delete_lease_token=%s)
                           RETURNING artifact_id""",
                       (now, str(artifact_id), lease_token, lease_token))
        if lease_token is not None and not cursor.fetchone():
            self.connection.rollback()
            raise RuntimeError("删除租约已失效")
        self.connection.commit()

    def stale_prepared(self, *, limit, now):
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT jsonb_build_object('artifact_id',artifact_id,'object_key',object_key)
                 FROM task_artifacts WHERE status='prepared' AND created_at<%s-INTERVAL '15 minutes'
                 ORDER BY created_at LIMIT %s""", (now, int(limit)))
        return [row[0] for row in cursor.fetchall()]

    def record_orphan_for_review(self, artifact_id, remote):
        cursor = self.connection.cursor()
        cursor.execute("UPDATE task_artifacts SET orphan_review_required=TRUE WHERE artifact_id=%s",
                       (str(artifact_id),))
        self.connection.commit()

    def remove_empty_prepared(self, artifact_id):
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM task_artifacts WHERE artifact_id=%s AND status='prepared'",
                       (str(artifact_id),))
        self.connection.commit()

    def delivery_attention_counts(self):
        cursor = self.connection.cursor()
        cursor.execute("""SELECT
            (SELECT COUNT(*) FROM delivery_events WHERE status IN ('unknown','permanent_failed')),
            (SELECT COUNT(*) FROM task_artifacts WHERE delete_attempts>=8 AND status<>'deleted'),
            (SELECT COUNT(*) FROM task_artifacts WHERE orphan_review_required=TRUE AND status<>'deleted')""")
        row = cursor.fetchone()
        return {"mail_events": int(row[0]), "delete_exhausted": int(row[1]), "orphans": int(row[2])}


__all__ = ["PostgresDeliveryRepository"]
