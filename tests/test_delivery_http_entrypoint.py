import json
import unittest
from unittest.mock import patch

from delivery_http_entrypoint import main_handler


class Otp:
    def issue(self,email,ip): self.issued=(email,ip); return "challenge-1"
    def verify(self,challenge,code): return {"session_token":"session-secret","csrf_token":"csrf-secret"}
class Auth:
    def revoke(self,token): self.token=token
    def authenticate(self,*args,**kwargs): self.auth_args=(args,kwargs); return "u1"
class Tasks:
    def create_task(self,**values): self.created=values; return {"task_id":"TASK-1","status":"queued"}
    def task_progress(self,**values): self.progress=values; return {"task_id":"TASK-1","status":"running"}
    def continue_after_intent(self,**values): self.continued=values; return {"task_id":"TASK-1","current_stage":"P2"}
    def task_delivery(self,**values): self.delivery=values; return {"task_id":"TASK-1","artifacts":[]}
class Cursor:
    def execute(self,sql): self.sql=sql
    def fetchone(self): return (1,)
class Connection:
    def cursor(self): return Cursor()


class HttpEntrypointTests(unittest.TestCase):
    def setUp(self): self.otp=Otp(); self.auth=Auth(); self.tasks=Tasks(); self.services={"otp":self.otp,"auth":self.auth,"tasks":self.tasks,"download":lambda **kw:"https://signed"}
    def test_request_uses_trusted_gateway_ip_not_forwarded_header(self):
        event={"httpMethod":"POST","path":"/auth/otp/request","body":json.dumps({"email":"u@example.com"}),
               "headers":{"x-forwarded-for":"attacker"},"requestContext":{"sourceIp":"203.0.113.2"}}
        response=main_handler(event,services=self.services)
        self.assertEqual(response["statusCode"],202)
        self.assertEqual(json.loads(response["body"])["challenge_id"],"challenge-1")
        self.assertEqual(self.otp.issued[1],"203.0.113.2")
    def test_verify_sets_only_secure_http_only_session_cookie(self):
        event={"httpMethod":"POST","path":"/auth/otp/verify","body":json.dumps({"challenge_id":"c","code":"123456"})}
        response=main_handler(event,services=self.services)
        cookie=response["headers"]["Set-Cookie"]
        self.assertIn("Secure",cookie); self.assertIn("HttpOnly",cookie); self.assertNotIn("csrf-secret",cookie)
    def test_download_reads_session_from_cookie_and_csrf_header(self):
        captured={}
        def download(**kw): captured.update(kw); return "https://signed"
        self.services["download"]=download
        event={"httpMethod":"POST","path":"/delivery/download","headers":{"cookie":"research_session=s1","x-csrf-token":"c1"},
               "body":json.dumps({"task_id":"t","artifact_id":"a","filename":"报告.pdf"})}
        response=main_handler(event,services=self.services)
        self.assertEqual(response["statusCode"],200); self.assertEqual(captured["session_token"],"s1")

    def test_create_task_requires_session_and_csrf_and_enqueues(self):
        event={"httpMethod":"POST","path":"/tasks","headers":{"cookie":"research_session=s1","x-csrf-token":"c1"},
               "body":json.dumps({"topic":"CRISPR diagnostics","tier":"fast"})}
        response=main_handler(event,services=self.services)
        self.assertEqual(response["statusCode"],201)
        self.assertEqual(self.tasks.created["user_id"],"u1")
        self.assertTrue(self.auth.auth_args[1]["require_csrf"])

    def test_progress_is_owner_scoped(self):
        event={"httpMethod":"GET","path":"/tasks/TASK-1/progress","headers":{"cookie":"research_session=s1"}}
        response=main_handler(event,services=self.services)
        self.assertEqual(response["statusCode"],200)
        self.assertEqual(self.tasks.progress,{"user_id":"u1","task_id":"TASK-1"})

    def test_continue_requires_csrf_and_submits_clarification(self):
        event={"httpMethod":"POST","path":"/tasks/TASK-1/continue",
               "headers":{"cookie":"research_session=s1","x-csrf-token":"c1"},
               "body":json.dumps({"clarification":"聚焦检测机制"})}
        response=main_handler(event,services=self.services)
        self.assertEqual(response["statusCode"],202)
        self.assertEqual(self.tasks.continued,{"user_id":"u1","task_id":"TASK-1","clarification":"聚焦检测机制"})
        self.assertTrue(self.auth.auth_args[1]["require_csrf"])

    def test_delivery_is_owner_scoped(self):
        event={"httpMethod":"GET","path":"/tasks/TASK-1/delivery","headers":{"cookie":"research_session=s1"}}
        response=main_handler(event,services=self.services)
        self.assertEqual(response["statusCode"],200)
        self.assertEqual(self.tasks.delivery,{"user_id":"u1","task_id":"TASK-1"})

    def test_health_checks_database_without_exposing_configuration(self):
        services={**self.services,"connection":Connection()}
        response=main_handler({"httpMethod":"GET","path":"/health"},services=services)
        body=json.loads(response["body"])
        self.assertEqual(response["statusCode"],200); self.assertEqual(body["database"],"ok")
        self.assertNotIn("DATABASE_URL",response["body"])

    def test_real_entrypoint_rejects_missing_gateway_secret_before_connecting(self):
        with patch.dict("os.environ",{"EDGEONE_GATEWAY_SECRET":"expected"},clear=True):
            response=main_handler({"httpMethod":"GET","path":"/health","headers":{}})
        self.assertEqual(response["statusCode"],403)


if __name__ == "__main__": unittest.main()
