import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectContentPackageTests(unittest.TestCase):
    def test_canonical_package_records_required_decision_areas(self):
        package = (ROOT / "docs" / "项目总内容包.md").read_text(encoding="utf-8")
        for phrase in (
            "已确认的界面风格",
            "已确认的内容生成规则",
            "工程能力与状态",
            "工程问题沉淀入口",
            "强制同步流程",
            "navigation_title",
            "GitHub Pages",
            "版本查询参数",
        ):
            self.assertIn(phrase, package)

    def test_readme_points_to_canonical_package(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/项目总内容包.md", readme)

    def test_raw_experiment_directories_are_not_published_by_default(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for path in (
            "artifacts/automatic-boundary-replay/",
            "artifacts/claim-bound-pilot/",
            "artifacts/fresh-boundary-run/",
            "artifacts/narrative-bound-pilot/",
            "artifacts/narrative-loop/",
        ):
            self.assertIn(path, ignore)


if __name__ == "__main__":
    unittest.main()
