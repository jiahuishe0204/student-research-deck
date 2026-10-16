import re
import json
import unittest
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
REPORT_SOURCE = ROOT / "docs" / "验证稿-慢性植入神经接口-调研报告.md"
PPT_SOURCE = ROOT / "docs" / "验证稿-慢性植入神经接口-PPT内容包.md"


def normalized_url(value):
    parts = urlsplit(value)
    path = parts.path.rstrip("/") if parts.path != "/" else parts.path
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


class DeliveryReaderTests(unittest.TestCase):
    def test_browser_samples_match_reviewed_source_documents(self):
        self.assertEqual(REPORT_SOURCE.read_text(encoding="utf-8"),
                         (WEB / "sample-delivery" / "report.md").read_text(encoding="utf-8"))
        self.assertEqual(PPT_SOURCE.read_text(encoding="utf-8"),
                         (WEB / "sample-delivery" / "ppt-content.md").read_text(encoding="utf-8"))
        bundle = (WEB / "sample-delivery" / "data.js").read_text(encoding="utf-8")
        self.assertTrue(bundle.startswith("window.DELIVERY_SAMPLE="))
        payload = json.loads(bundle.removeprefix("window.DELIVERY_SAMPLE=").removesuffix(";\n"))
        self.assertEqual(payload["report"], REPORT_SOURCE.read_text(encoding="utf-8"))
        self.assertEqual(payload["slides"], PPT_SOURCE.read_text(encoding="utf-8"))

    def test_sample_contains_complete_report_and_twelve_slide_pages(self):
        report = REPORT_SOURCE.read_text(encoding="utf-8")
        ppt = PPT_SOURCE.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"^# (?!#)", report, flags=re.MULTILINE)), 9)
        self.assertEqual(len(re.findall(r"^## 第\s*\d+\s*页[｜|]", ppt, flags=re.MULTILINE)), 12)
        for label in ("上屏文字", "配图建议", "讲稿", "来源"):
            self.assertEqual(len(re.findall(rf"^{label}：?", ppt, flags=re.MULTILINE)), 12)
        self.assertEqual(len(re.findall(r"^目录标题：", ppt, flags=re.MULTILINE)), 12)

    def test_ppt_directory_uses_reviewed_navigation_titles(self):
        ppt = PPT_SOURCE.read_text(encoding="utf-8")
        script = (WEB / "delivery.js").read_text(encoding="utf-8")
        expected = ("研究背景与核心问题", "植入后的界面反应", "柔性电极的界面优势", "水凝胶分类",
                    "水凝胶的材料设计", "界面性能与评价指标", "短期植入表现", "长期稳定性评价",
                    "神经信号记录", "神经刺激效果", "现有局限", "展望")
        self.assertEqual(re.findall(r"^目录标题：\s*(.+)$", ppt, flags=re.MULTILINE), list(expected))
        self.assertIn("navigationTitle", script)
        self.assertIn("item.navigationTitle", script)

    def test_future_ppt_prompt_generates_natural_navigation_titles(self):
        p6 = (ROOT / "prompts" / "P6-ppt.md").read_text(encoding="utf-8")
        p9 = (ROOT / "prompts" / "P9-final.md").read_text(encoding="utf-8")
        for phrase in ("目录短标题 navigation_title", "一般 4—12 个汉字", "水凝胶分类", "后续研究页直接写“展望”"):
            self.assertIn(phrase, p6)
        self.assertIn("保留 navigation_title", p9)

    def test_source_projection_has_six_papers_and_five_figure_pages(self):
        markdown = REPORT_SOURCE.read_text(encoding="utf-8") + PPT_SOURCE.read_text(encoding="utf-8")
        urls = {normalized_url(value) for value in re.findall(r"\[[^\]]+\]\((https?://[^\s)]+)\)", markdown)}
        figure_urls = {value for value in urls if "/figure/" in value}
        paper_urls = urls - figure_urls
        self.assertEqual(len(paper_urls), 6)
        self.assertEqual(len(figure_urls), 5)

    def test_figure_recommendations_name_exact_figure_and_panels(self):
        report = REPORT_SOURCE.read_text(encoding="utf-8")
        ppt = PPT_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("[查看原文图页]", report)
        self.assertNotIn("[查看原文图页]", ppt)
        self.assertNotIn("指定使用", report + ppt)
        self.assertIn("推荐使用", report + ppt)
        for label in ("查看原文 Figure 1", "查看原文 Figure 2", "查看原文 Figure 3", "查看原文 Figure 4"):
            self.assertIn(label, report + ppt)
        for panel_note in ("分图 b（1 kHz 阻抗）", "分图 d（CV）", "分图 a（平均挤出力）", "a–c 为离子导电水凝胶"):
            self.assertIn(panel_note, report + ppt)

    def test_future_generation_requires_exact_figure_and_panel_guidance(self):
        prompts = "\n".join(
            (ROOT / "prompts" / name).read_text(encoding="utf-8")
            for name in ("P4-evidence.md", "P5-report.md", "P6-ppt.md")
        )
        self.assertIn("分图 a/b/c", prompts)
        self.assertIn("具体采用原文 Figure/Fig. 几", prompts)
        self.assertIn("不能只写“查看原图”", prompts)
        self.assertIn("无法确定具体图号或分图时不引用该图", prompts)
        self.assertIn("推荐自行绘制……示意图", prompts)
        self.assertIn("不得在客户内容中写“需补充图源”", prompts)

    def test_customer_ppt_uses_positive_drawing_guidance_when_no_exact_figure(self):
        ppt = PPT_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("需补充图源", ppt)
        self.assertNotIn("不使用未经许可的原图", ppt)
        self.assertGreaterEqual(ppt.count("推荐自行绘制"), 9)

    def test_secondary_navigation_has_sliding_indicator_and_content_motion(self):
        script = (WEB / "delivery.js").read_text(encoding="utf-8")
        motion = (WEB / "delivery-motion.css").read_text(encoding="utf-8")
        self.assertIn("index-active-indicator", script)
        self.assertIn("updateIndexIndicator", script)
        self.assertIn("animateIndexedContent", script)
        self.assertIn("--index-x", motion)
        self.assertIn("linear-gradient(100deg, #ece8f8", motion)
        self.assertIn("cubic-bezier(.65, 0, .35, 1)", motion)
        self.assertIn("translateY(var(--index-y, 0))", motion)
        self.assertNotIn(".index-active-indicator::before", motion)
        self.assertIn("translateY(${direction * 14}px)", script)
        self.assertIn("scrollbar-color: rgba(102, 88, 181, .22) transparent", motion)
        self.assertIn("const canReuse", script)
        self.assertIn("items[itemIndex].title", script)

    def test_result_page_removes_status_explainer_and_keeps_login_pending_honest(self):
        html = (WEB / "delivery.html").read_text(encoding="utf-8")
        for text in ("真实内容样本 / 人工学术润色", "你正在查看什么", "本地可用", "真实样本"):
            self.assertNotIn(text, html)
        self.assertNotIn('class="truth-card"', html)
        self.assertIn("邮箱登录", html)
        self.assertIn("待接入", html)
        self.assertIn('aria-disabled="true"', html)
        self.assertNotIn("交付结果</span>", html)
        self.assertNotIn("产品已经上线", html)
        self.assertIn("不等于已上线", html)

    def test_homepage_uses_the_delivery_visual_language(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        theme = (WEB / "home-delivery-theme.css").read_text(encoding="utf-8")
        rules = (ROOT / "docs" / "界面视觉一致性规则.md").read_text(encoding="utf-8")
        self.assertIn("home-delivery-theme.css", html)
        self.assertIn("brand-mark report-mark", html)
        for token in ("#f7f6f3", "#6658b5", "var(--font-editorial)", ".command-panel", ".plan-grid .featured"):
            self.assertIn(token, theme)
        self.assertIn("首页、题目确认、任务进行中、交付结果", rules)
        self.assertIn("不得只保留在样本", rules)

    def test_homepage_ppt_preview_pages_are_interactive(self):
        script = (WEB / "app.js").read_text(encoding="utf-8")
        theme = (WEB / "home-delivery-theme.css").read_text(encoding="utf-8")
        for phrase in ("slidePreviewPages", "data-slide-preview", "renderSlidePreview", "aria-pressed"):
            self.assertIn(phrase, script)
        for label in ("问题", "路线", "证据"):
            self.assertIn(f"label:'{label}'", script)
        self.assertIn("cubic-bezier(.65, 0, .35, 1)", theme)
        self.assertNotIn(".slide-list button.active::before", theme)

    def test_homepage_workflow_steps_share_alignment_rows(self):
        theme = (WEB / "home-delivery-theme.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", theme)
        self.assertIn("border: 1px solid #e0dce8", theme)
        self.assertIn("min-height: 31px", theme)
        self.assertIn("min-height: 50px", theme)

    def test_delivery_page_inherits_homepage_lavender_background(self):
        result_css = (WEB / "delivery-result.css").read_text(encoding="utf-8")
        rules = (ROOT / "docs" / "界面视觉一致性规则.md").read_text(encoding="utf-8")
        for token in ("radial-gradient", "#f4f1fa", "#f8f7f4", "background-attachment: fixed"):
            self.assertIn(token, result_css)
        self.assertIn("卡片外背景应继承同一渐变", rules)

    def test_current_download_is_two_character_menu_with_windows_friendly_formats(self):
        html = (WEB / "delivery.html").read_text(encoding="utf-8")
        script = (WEB / "delivery.js").read_text(encoding="utf-8")
        self.assertRegex(html, r'id="download-trigger"[^>]*>下载</button>')
        self.assertNotIn("下载当前内容 .md", html)
        self.assertNotIn("下载完整样本", html)
        for value in ('data-format="markdown"', 'data-format="html"', 'data-format="pdf"'):
            self.assertIn(value, html)
        self.assertIn("text/html;charset=utf-8", script)
        self.assertIn("content.querySelectorAll('button').forEach(button => button.remove())", script)
        self.assertIn("@page{size:A4", script)
        self.assertIn("不是线上生成结果", script)
        self.assertIn("printWindow.print()", script)
        self.assertIn("Microsoft Print to PDF", script)

    def test_delivery_tabs_have_sliding_indicator_and_directional_content_motion(self):
        html = (WEB / "delivery.html").read_text(encoding="utf-8")
        script = (WEB / "delivery.js").read_text(encoding="utf-8")
        motion_css = (WEB / "delivery-motion.css").read_text(encoding="utf-8")
        self.assertIn('class="view-tab-indicator"', html)
        self.assertIn("updateTabIndicator(view)", script)
        self.assertIn("translateX", script)
        self.assertIn("prefers-reduced-motion: reduce", script)
        self.assertIn("transition: transform 380ms", motion_css)
        self.assertIn("margin-top: 14px", motion_css)

    def test_file_url_bundle_and_report_icon_replace_fetch_only_and_snowflake_ui(self):
        html = (WEB / "delivery.html").read_text(encoding="utf-8")
        script = (WEB / "delivery.js").read_text(encoding="utf-8")
        self.assertNotIn("跳到交付正文", html)
        self.assertNotIn("✳", html)
        self.assertIn('class="brand-mark report-mark"', html)
        self.assertLess(html.index("./sample-delivery/data.js"), html.index("./delivery.js"))
        self.assertIn("window.DELIVERY_SAMPLE?.report", script)


if __name__ == "__main__":
    unittest.main()
