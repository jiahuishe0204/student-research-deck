import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProductionWebAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (ROOT / "web" / "delivery.js").read_text(encoding="utf-8")
        cls.html = (ROOT / "web" / "delivery.html").read_text(encoding="utf-8")

    def test_task_query_uses_owner_scoped_production_delivery(self):
        self.assertIn("searchParams.get('task')", self.script)
        self.assertIn("/delivery`, { credentials: 'include'", self.script)
        self.assertIn("final.final_report?.markdown", self.script)
        self.assertIn("pptToMarkdown(final.final_ppt", self.script)

    def test_private_download_requires_csrf_and_never_embeds_secret(self):
        self.assertIn("sessionStorage.getItem('research_csrf_token')", self.script)
        self.assertIn("'/delivery/download'", self.script)
        self.assertIn("'X-CSRF-Token': csrf", self.script)
        self.assertNotIn("CONTROL_API_BASE_URL", self.script)

    def test_sample_mode_and_existing_styles_remain(self):
        self.assertIn("window.DELIVERY_SAMPLE?.report", self.script)
        self.assertIn('delivery.css?v=3', self.html)
        self.assertIn('delivery-result.css?v=6', self.html)


if __name__ == "__main__":
    unittest.main()
