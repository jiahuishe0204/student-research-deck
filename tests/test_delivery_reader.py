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
    def test_real_case_export_keeps_navigation_title_and_full_title(self):
        from tests.export_readable_delivery import delivery_markdown

        final = {"final_ppt": {"deck_title": "测试", "storyline": "故事", "pages": [{
            "page_id": "P1", "navigation_title": "免疫微环境异质性",
            "title": "单细胞分析显示肿瘤免疫微环境存在细胞状态差异",
            "purpose": "解释异质性", "on_slide_text": ["要点"],
            "visual_suggestion": "", "figure_refs": [],
            "source_citations": [{"source_id": "SRC-1", "short_vancouver": "Xiang L, et al. Int J Mol Sci. 2024;25(17)."}],
            "speaker_notes": "讲稿", "evidence_ids": ["EV1"],
        }]}, "open_issues": []}
        sources = [{"source_id": "SRC-1", "authors": ["Lingyan Xiang", "Jie Rao", "Jingping Yuan", "Ting Xie"],
                    "journal": "International journal of molecular sciences", "year": "2024", "volume": "25",
                    "issue": "17", "pages": "", "doi": "10.3390/ijms25179482"}]
        markdown = delivery_markdown(final, sources)
        self.assertIn("## 第 1 页｜免疫微环境异质性", markdown)
        self.assertIn("**副标题**：单细胞分析显示肿瘤免疫微环境存在细胞状态差异", markdown)
        self.assertIn("**参考来源**", markdown)
        self.assertIn("Xiang L, Rao J, Yuan J, et al. Int J Mol Sci. 2024;25(17). doi:[10.3390/ijms25179482](https://doi.org/10.3390/ijms25179482)", markdown)
        self.assertNotIn("EV1", markdown)
        self.assertNotIn("配图建议与图源", markdown)

    def test_figure_guidance_is_omitted_without_a_direct_link_and_shown_with_one(self):
        from tests.export_readable_delivery import delivery_markdown

        page = {"page_id": "P1", "navigation_title": "细胞状态", "title": "完整标题", "purpose": "说明",
                "on_slide_text": ["要点"], "visual_suggestion": "展示细胞状态差异", "figure_refs": [],
                "source_citations": [], "speaker_notes": "讲稿", "evidence_ids": ["EV::1"]}
        final = {"final_ppt": {"deck_title": "测试", "storyline": "故事", "pages": [page]}, "open_issues": []}
        markdown = delivery_markdown(final, [])
        self.assertNotIn("配图建议与图源", markdown)
        page["figure_refs"] = [{"figure_id": "SRC-1:Fig2", "locator": "Figure 2 https://publisher.example/article/figure/2",
                                "intended_use": "展示细胞状态差异", "reuse_status": "unknown"}]
        markdown = delivery_markdown(final, [])
        self.assertIn("配图建议与图源", markdown)
        self.assertIn("https://publisher.example/article/figure/2", markdown)
        self.assertNotIn("EV::1", markdown)

    def test_reader_renders_short_main_title_and_full_subtitle(self):
        script = (WEB / "delivery.js").read_text(encoding="utf-8")
        self.assertIn("blocks['副标题'] || match[2].trim()", script)
        self.assertIn("<h1>${escapeHtml(page.navigationTitle)}</h1><p class=\"slide-subtitle\">${escapeHtml(page.title)}</p>", script)
        self.assertIn("参考来源|讲稿", script)
        self.assertIn("function renderFigureBlock(markdown)", script)
        self.assertIn("配图建议与图源', markdown", script)
        self.assertTrue((WEB / "delivery-title-hierarchy.css").exists())

    def test_download_menu_exports_complete_report_and_entire_slide_package(self):
        for html_path in (WEB / "delivery.html", WEB / "single-cell-delivery.html"):
            html = html_path.read_text(encoding="utf-8")
            for artifact in ("report", "slides"):
                for fmt in ("markdown", "html", "pdf"):
                    self.assertIn(f'data-kind="{artifact}" data-format="{fmt}"', html)
            self.assertIn("全部页面与讲稿", html)
        script = (WEB / "delivery.js").read_text(encoding="utf-8")
        self.assertIn("function artifactInfo(kind)", script)
        self.assertIn("kind === 'report' ? state.report : state.slides", script)
        self.assertIn("function completeArtifactHtml(kind)", script)
        self.assertIn("function printArtifactAsPdf(kind)", script)
        self.assertNotIn("state.slidePages[state.selectedSlide].number}.md", script)

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

    def test_customer_ppt_hides_internal_evidence_ids_but_keeps_traceability(self):
        script = (WEB / "app.js").read_text(encoding="utf-8")
        p6 = (ROOT / "prompts" / "P6-ppt.md").read_text(encoding="utf-8")
        p9 = (ROOT / "prompts" / "P9-final.md").read_text(encoding="utf-8")
        package = (ROOT / "docs" / "项目总内容包.md").read_text(encoding="utf-8")
        self.assertIn("data-evidence-ids", script)
        self.assertIn("evidence_ids||[]", script)
        self.assertIn("参考来源：", script)
        self.assertNotIn("<span>${escapeHtml((page.evidence_ids||[]).join", script)
        for text in (p6, p9, package):
            self.assertIn("EV::...", text)
            self.assertIn("客户可见", text)
            self.assertIn("evidence_ids", text)

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

    def test_roadmap_uses_the_same_lavender_visual_language(self):
        html = (WEB / "roadmap.html").read_text(encoding="utf-8")
        css = (WEB / "roadmap.css").read_text(encoding="utf-8")
        rules = (ROOT / "docs" / "界面视觉一致性规则.md").read_text(encoding="utf-8")
        self.assertIn("home-delivery-theme.css?v=7", html)
        self.assertIn("brand-mark report-mark", html)
        for token in ("#f7f6f3", "#f5f2fc", "var(--font-editorial)", "#b4aad8"):
            self.assertIn(token, css)
        self.assertNotIn("rgba(98,245,177", css)
        self.assertIn("执行版图等辅助页面不得继续沿用历史绿色主题", rules)

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

    def test_homepage_plan_prices_stay_on_one_line(self):
        theme = (WEB / "home-delivery-theme.css").read_text(encoding="utf-8")
        rules = (ROOT / "docs" / "界面视觉一致性规则.md").read_text(encoding="utf-8")
        self.assertIn("flex-wrap: nowrap", theme)
        self.assertIn("white-space: nowrap", theme)
        self.assertIn("价格信息必须保持单行", rules)

    def test_delivery_page_inherits_homepage_lavender_background(self):
        result_css = (WEB / "delivery-result.css").read_text(encoding="utf-8")
        rules = (ROOT / "docs" / "界面视觉一致性规则.md").read_text(encoding="utf-8")
        for token in ("radial-gradient", "#f4f1fa", "#f8f7f4", "background-attachment: fixed"):
            self.assertIn(token, result_css)
        self.assertIn("卡片外背景应继承同一渐变", rules)

    def test_download_menu_offers_complete_report_and_complete_ppt(self):
        html = (WEB / "delivery.html").read_text(encoding="utf-8")
        script = (WEB / "delivery.js").read_text(encoding="utf-8")
        self.assertRegex(html, r'id="download-trigger"[^>]*>下载</button>')
        for value in ('data-kind="report" data-format="markdown"', 'data-kind="report" data-format="html"', 'data-kind="report" data-format="pdf"', 'data-kind="slides" data-format="markdown"', 'data-kind="slides" data-format="html"', 'data-kind="slides" data-format="pdf"'):
            self.assertIn(value, html)
        self.assertIn("kind === 'report' ? state.report : state.slides", script)
        self.assertIn("完整网页文件", html)
        self.assertIn("打印窗口后保存为 PDF", html)
        self.assertIn("state.slidePages.map(page =>", script)

    def test_download_layout_is_the_persistent_simple_delivery_baseline(self):
        rules = (ROOT / "docs" / "项目总内容包.md").read_text(encoding="utf-8")
        script = (WEB / "delivery.js").read_text(encoding="utf-8")
        for phrase in ("不额外增加封面、自动目录或装饰性页面", "完整保留报告或 PPT 内容包原文", "每页分隔并保留页码、短主标题与完整副标题"):
            self.assertIn(phrase, rules)
        self.assertIn("@page{size:A4;margin:18mm 17mm}", script)
        self.assertIn("state.slidePages.map(page =>", script)
        self.assertIn(".slide-document{padding-bottom:22px;margin-bottom:30px;border-bottom:1px solid #e6e2e9;break-after:page}", script)
        self.assertIn("完整交付文件 · 共 ${kind === 'report' ? state.reportSections.length + ' 个报告章节'", script)

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
