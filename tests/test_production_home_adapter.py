import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProductionHomeAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "web" / "mvp.css").read_text(encoding="utf-8")

    def test_email_otp_controls_are_present_but_hidden_by_default(self):
        self.assertIn('id="production-auth" class="production-auth" hidden', self.html)
        self.assertIn('id="auth-email"', self.html)
        self.assertIn('id="auth-code"', self.html)

    def test_production_mode_requires_confirmed_healthy_edgeone_gateway(self):
        self.assertIn("fetch('/api/health'", self.script)
        self.assertIn("data.runtime==='edgeone-gateway'&&data.ok===true", self.script)
        self.assertIn("if(!productionMode){const local=", self.script)
        self.assertIn("form.querySelector('.primary').disabled=true", self.script)

    def test_otp_and_mutating_requests_use_cookie_and_tab_scoped_csrf(self):
        self.assertIn("credentials:'include'", self.script)
        self.assertIn("sessionStorage.setItem(csrfKey,response.csrf_token)", self.script)
        self.assertIn("productionRequest('/auth/otp/request'", self.script)
        self.assertIn("productionRequest('/auth/otp/verify'", self.script)
        self.assertNotIn("localStorage.setItem(csrfKey", self.script)

    def test_production_task_flow_covers_create_confirm_poll_and_delivery(self):
        self.assertIn("productionRequest('/api/intent'", self.script)
        self.assertIn("intent_ticket:currentIntentTicket", self.script)
        self.assertIn("currentIntentTicket=null", self.script)
        self.assertIn("productionRequest('/tasks'", self.script)
        self.assertIn("/continue`,{method:'POST',csrf:true", self.script)
        self.assertIn("/progress`)", self.script)
        self.assertIn("delivery.html?task=", self.script)

    def test_local_demo_flow_remains_available(self):
        self.assertIn("request('/api/tasks'", self.script)
        self.assertIn("request('/api/intent'", self.script)
        self.assertIn("request('/api/plan'", self.script)

    def test_new_topic_resets_previous_run_and_refreshes_usage_after_failed_finalization(self):
        self.assertIn("function resetRunForNewTopic()", self.script)
        self.assertIn("resetRunForNewTopic();currentTopic=submittedTopic", self.script)
        self.assertIn("finally{await refreshTaskUsage().catch(()=>{})", self.script)
        self.assertIn("app.js?v=11", self.html)
        self.assertIn("这条任务缺少已保存的规划或来源", self.script)

    def test_auth_panel_reuses_existing_visual_language(self):
        self.assertIn(".production-auth", self.styles)
        self.assertIn("var(--accent)", self.styles)
        self.assertIn("var(--line)", self.styles)


if __name__ == "__main__":
    unittest.main()
