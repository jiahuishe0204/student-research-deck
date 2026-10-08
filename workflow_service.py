"""Application service that binds stages to prompts, routes, and model calls."""

import copy
import json
import re
import threading
from pathlib import Path

from contracts import load_contract
from model_client import deepseek_json
from workflow_validation import (
    validate_claims, validate_evidence, validate_final, validate_intent, validate_plan,
    validate_ppt, validate_report, validate_screen, validate_verification,
)


def add_usage(total, partial):
    for key in total:
        total[key] += int(partial.get(key, 0) or 0)


class WorkflowService:
    CLAIMS_PER_BATCH_LIMIT = 6
    def __init__(self, api_key, model_router, system_prompt, stage_prompts, model_client=deepseek_json, usage_ledger=None, model_limits=None):
        self.api_key = api_key
        self.model_router = model_router
        self.system_prompt = system_prompt
        self.stage_prompts = dict(stage_prompts)
        self.model_client = model_client
        self.usage_ledger = usage_ledger
        self.model_limits = model_limits or {}
        self._context = threading.local()

    @classmethod
    def from_project(cls, api_key, model_router, root, model_client=deepseek_json, usage_ledger=None, model_limits=None):
        root = Path(root)
        registry = json.loads((root / "config" / "prompt-stages.json").read_text(encoding="utf-8"))
        system_prompt = (root / registry["global_prompt"]).read_text(encoding="utf-8")
        stage_prompts = {}
        for entry in registry.get("stages", []):
            stage = entry.get("id")
            prompt_path = entry.get("prompt")
            if not stage or not prompt_path or stage in stage_prompts:
                raise ValueError("提示词阶段注册表无效")
            stage_prompts[stage] = (root / prompt_path).read_text(encoding="utf-8")
        return cls(api_key, model_router, system_prompt, stage_prompts, model_client, usage_ledger, model_limits)

    def set_task_context(self, task_id):
        self._context.task_id = task_id

    @staticmethod
    def _claim_complexity(claim, evidence_by_id):
        score = 1
        if claim.get("claim_type") in {"causal", "efficacy", "safety", "approval"}:
            score += 2
        score += {"medium": 1, "high": 2}.get(claim.get("risk_level"), 0)
        cited = claim.get("cited_evidence_ids", [])
        if len(cited) >= 3:
            score += 1
        evidence_chars = sum(len(json.dumps(evidence_by_id.get(item, {}), ensure_ascii=False)) for item in cited)
        if evidence_chars > 3000:
            score += 1
        text = str(claim.get("atomic_claim", ""))
        if len(re.findall(r"\d+(?:\.\d+)?", text)) >= 2:
            score += 1
        return score, evidence_chars

    @classmethod
    def _verification_batches(cls, items, evidence_by_id, upgrade):
        max_claims = 4 if upgrade else 8
        max_complexity = 14 if upgrade else 16
        max_evidence_chars = 10000 if upgrade else 14000
        batches, current = [], []
        complexity_total = evidence_chars_total = 0
        for item in items:
            complexity, evidence_chars = cls._claim_complexity(item, evidence_by_id)
            over_limit = current and (
                len(current) >= max_claims
                or complexity_total + complexity > max_complexity
                or evidence_chars_total + evidence_chars > max_evidence_chars
            )
            if over_limit:
                batches.append(current)
                current, complexity_total, evidence_chars_total = [], 0, 0
            current.append(item)
            complexity_total += complexity
            evidence_chars_total += evidence_chars
        if current:
            batches.append(current)
        return batches

    @classmethod
    def _verification_output_limit(cls, items, evidence_by_id, upgrade):
        complexity = sum(cls._claim_complexity(item, evidence_by_id)[0] for item in items)
        ceiling = 3200 if upgrade else 3800
        floor = 2200 if upgrade else 1200
        return min(ceiling, max(floor, 650 + len(items) * 220 + complexity * 70))

    def generate(self, stage, tier, payload, validator=None, *, upgrade=False, max_tokens=6000, max_attempts=2, request_timeout=300):
        if stage not in self.stage_prompts:
            raise ValueError("阶段 %s 缺少提示词" % stage)
        route = self.model_router.for_stage(stage, tier, upgrade=upgrade)
        task_id = getattr(self._context, "task_id", "unassigned")
        input_bytes = len((self.system_prompt + self.stage_prompts[stage] + json.dumps(payload, ensure_ascii=False)).encode("utf-8"))

        def record(attempt, status, usage, detail):
            if self.usage_ledger:
                self.usage_ledger.record(task_id, stage, route["model"], route["effort"], attempt, status, usage, detail)

        def guard(attempt):
            if self.usage_ledger:
                self.usage_ledger.guard(task_id, route["model"], self.model_limits, max_tokens, input_bytes)
        output, usage = self.model_client(
            self.api_key,
            route["model"],
            self.system_prompt,
            self.stage_prompts[stage],
            payload,
            route["effort"],
            validator,
            max_tokens,
            max_attempts,
            request_timeout,
            record,
            guard,
        )
        return output, usage, route

    @staticmethod
    def _tier(value):
        tier = value or "fast"
        if tier not in ("fast", "deep"):
            raise ValueError("版本无效")
        return tier

    @staticmethod
    def _ids(records, field, error, *, unique=True):
        if not isinstance(records, list):
            raise ValueError(error)
        values = [str(item.get(field, "")).strip() for item in records if isinstance(item, dict)]
        if len(values) != len(records) or any(not value for value in values) or (unique and len(values) != len(set(values))):
            raise ValueError(error)
        return values

    @staticmethod
    def _text_chunks(text, limit=1200):
        text = str(text or "")
        if not text:
            return [""]
        chunks, current = [], ""
        for paragraph in text.splitlines(keepends=True):
            while len(paragraph) > limit:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(paragraph[:limit])
                paragraph = paragraph[limit:]
            if current and len(current) + len(paragraph) > limit:
                chunks.append(current)
                current = ""
            current += paragraph
        if current or not chunks:
            chunks.append(current)
        return chunks

    def create_intent(self, topic, tier="fast"):
        topic = str(topic or "").strip()
        tier = self._tier(tier)
        if not 2 <= len(topic) <= 500:
            raise ValueError("请输入 2—500 字的主题并选择有效版本")
        output, usage, _ = self.generate(
            "P1", tier, {"topic": topic, "tier": tier, "runtime_config": {"language": "zh-CN"}},
            validate_intent, max_attempts=3,
        )
        return output, usage

    def create_plan(self, topic, clarification="", tier="fast"):
        topic = str(topic or "").strip()
        clarification = str(clarification or "").strip()
        tier = self._tier(tier)
        if not 2 <= len(topic) <= 500:
            raise ValueError("规划输入无效")
        normalized = topic + (("；用户澄清：" + clarification) if clarification else "")
        output, usage, _ = self.generate(
            "P2", tier, {
                "intent": {"domain": "life_science", "normalized_topic": normalized, "tier": tier, "need_clarification": False},
                "tier": tier, "available_sources": ["PubMed", "Europe PMC", "Crossref", "EPO OPS", "official"],
                "runtime_config": {"source_limit": 19 if tier == "deep" else 10, "language": "zh-CN"},
            }, validate_plan, max_tokens=8000, max_attempts=3,
        )
        return output, usage

    def screen_sources(self, topic, plan, candidates, tier="fast"):
        topic = str(topic or "").strip()
        tier = self._tier(tier)
        if not 2 <= len(topic) <= 500 or not isinstance(plan, dict):
            raise ValueError("筛选主题或规划无效")
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 30:
            raise ValueError("候选资料数量必须为 1—30 条")
        candidate_ids = self._ids(candidates, "source_id", "候选资料 source_id 缺失或重复")
        keep_max = 8 if tier == "deep" else 4
        keys = ("source_id", "source", "title", "abstract", "year", "access", "url")
        compact = [{key: item.get(key) for key in keys} for item in candidates]
        output, usage, _ = self.generate(
            "P3", tier,
            {"topic": topic, "plan": plan, "candidate_sources": compact, "limits": {"keep_max": keep_max, "tier": tier}, "output_contract": load_contract("P3")},
            lambda value: validate_screen(value, candidate_ids, keep_max),
        )
        return output, usage

    def extract_evidence(self, source_record, question_ids, tier="fast"):
        tier = self._tier(tier)
        if not isinstance(source_record, dict) or not isinstance(question_ids, list):
            raise ValueError("证据提取输入无效")
        source_id = str(source_record.get("source_id", "")).strip()
        source_text = str(source_record.get("abstract", "")).strip()
        if not source_id:
            raise ValueError("来源缺少 source_id")
        if not source_text:
            output = {"evidence_version": "1.0", "source_id": source_id, "extraction_status": "no_extractable_evidence", "reading_scope": "metadata_only", "evidence_records": [], "figure_records": [], "no_extractable_reason": "当前来源没有可读取摘要或正文"}
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}
            return validate_evidence(output, source_id, source_record.get("access")), usage
        keys = ("source_id", "source", "title", "authors", "journal", "year", "url", "access")
        compact = {key: source_record.get(key) for key in keys}
        output, usage, _ = self.generate(
            "P4", tier,
            {"source_record": compact, "source_text": source_text, "question_ids": question_ids, "output_contract": load_contract("P4")},
            lambda value: validate_evidence(value, source_id, source_record.get("access")),
        )
        return output, usage

    def create_report(self, intent, plan, evidence_records, tier="fast"):
        tier = self._tier(tier)
        if not isinstance(intent, dict) or not isinstance(plan, dict) or not isinstance(evidence_records, list):
            raise ValueError("报告生成输入无效")
        if not 1 <= len(evidence_records) <= 100:
            raise ValueError("至少需要 1 条且最多处理 100 条证据")
        evidence_ids = self._ids(evidence_records, "evidence_id", "证据编号缺失或重复")
        output, usage, _ = self.generate(
            "P5", tier,
            {"intent": intent, "plan": plan, "evidence_records": evidence_records, "tier": tier, "output_contract": load_contract("P5")},
            lambda value: validate_report(value, evidence_ids),
        )
        return output, usage

    def create_ppt(self, intent, report, evidence_records, figure_records=None, constraints=None, tier="fast"):
        tier = self._tier(tier)
        figure_records = [] if figure_records is None else figure_records
        constraints = {} if constraints is None else constraints
        if not isinstance(intent, dict) or not isinstance(report, dict) or not isinstance(evidence_records, list) or not isinstance(figure_records, list) or not isinstance(constraints, dict):
            raise ValueError("PPT 内容包输入无效")
        evidence_ids = self._ids(evidence_records, "evidence_id", "PPT 输入包含无效证据编号", unique=False)
        figure_ids = self._ids(figure_records, "figure_id", "PPT 输入包含无效图片编号", unique=False)
        output, usage, _ = self.generate(
            "P6", tier,
            {"intent": intent, "report": report, "evidence_records": evidence_records, "figure_records": figure_records, "allowed_evidence_ids": evidence_ids, "allowed_figure_ids": figure_ids, "constraints": constraints, "output_contract": load_contract("P6")},
            lambda value: validate_ppt(value, evidence_ids, figure_ids),
        )
        return output, usage

    def assemble_final(self, verification, report, ppt, claim_ids, source_ids, evidence_ids, evidence_version="1.0", tier="fast"):
        tier = self._tier(tier)
        if not all(isinstance(item, list) for item in (claim_ids, source_ids, evidence_ids)) or not all(isinstance(item, dict) for item in (verification, report, ppt)):
            raise ValueError("最终装配输入无效")
        output, usage, _ = self.generate(
            "P9", tier,
            {"verification_results": verification, "draft_report": report, "draft_ppt": ppt, "claim_ids": claim_ids, "source_ids": source_ids, "evidence_ids": evidence_ids, "evidence_version": str(evidence_version), "output_contract": load_contract("P9")},
            lambda value: validate_final(value, claim_ids, source_ids, evidence_ids, verification), max_tokens=12000, max_attempts=3,
        )
        return output, usage

    def assemble_final_deterministic(self, verification, report, ppt, claims, source_ids, evidence_ids, evidence_version="1.0"):
        """Apply verified edits without asking the model to reproduce the full delivery."""
        claim_ids = self._ids(claims, "claim_id", "最终装配声明编号缺失或重复")
        results = {item["claim_id"]: item for item in verification.get("results", [])}
        if set(results) != set(claim_ids):
            raise ValueError("最终装配必须包含全部声明的核验结果")
        markdown = str(report.get("report_markdown", ""))
        pages = copy.deepcopy(ppt.get("pages", []))
        pages_by_id = {page.get("page_id"): page for page in pages}
        original_markdown = markdown
        original_pages = copy.deepcopy(pages_by_id)
        open_issues = list(report.get("open_issues", []))
        change_log = []
        action_names = {"keep": "kept", "revise": "revised", "remove": "removed", "mark_unverified": "marked_unverified"}

        def replace_once(text, original, replacement):
            candidates = [original, original.rstrip("。；;，,"), original.strip()]
            if "：" in original and len(original.rsplit("：", 1)[-1].strip()) >= 6:
                candidates.append(original.rsplit("：", 1)[-1].strip().rstrip("。；;，,"))
            for candidate in dict.fromkeys(item for item in candidates if item):
                if candidate in text:
                    return text.replace(candidate, replacement, 1), True
            return text, False

        for claim in claims:
            result = results[claim["claim_id"]]
            action = result["action"]
            change_log.append({"claim_id": claim["claim_id"], "action": action_names[action], "reason": result["explanation"]})
            if action == "keep":
                continue
            original = claim["original_text"]
            replacement = result.get("revised_claim") or ""
            if action == "mark_unverified":
                replacement = (replacement or original) + "（未核实）"
            located = False
            if claim["location_type"] == "report_section":
                markdown, located = replace_once(markdown, original, replacement)
                if not located and claim["section_or_page_id"].startswith("open_issues_"):
                    open_issues.append(replacement)
                    located = True
            else:
                page = pages_by_id.get(claim["section_or_page_id"])
                if page:
                    field = "speaker_notes" if claim["location_type"] == "ppt_speaker_note" else "on_slide_text"
                    if field == "speaker_notes":
                        page[field], located = replace_once(page.get(field, ""), original, replacement)
                    else:
                        for index, line in enumerate(page.get(field, [])):
                            page[field][index], located = replace_once(line, original, replacement)
                            if located:
                                break
            if not located:
                originally_located = False
                if claim["location_type"] == "report_section":
                    _, originally_located = replace_once(original_markdown, original, "")
                else:
                    original_page = original_pages.get(claim["section_or_page_id"], {})
                    original_text = original_page.get("speaker_notes", "") if claim["location_type"] == "ppt_speaker_note" else "\n".join(original_page.get("on_slide_text", []))
                    _, originally_located = replace_once(original_text, original, "")
                if originally_located:
                    if replacement and claim["location_type"] == "report_section":
                        markdown += "\n\n核验修订：%s" % replacement
                    elif replacement and page and claim["location_type"] == "ppt_speaker_note":
                        page["speaker_notes"] = (page.get("speaker_notes", "") + " 核验修订：" + replacement).strip()
                    elif replacement and page:
                        page.setdefault("on_slide_text", []).append("核验修订：" + replacement)
                    located = True
                if not located:
                    raise ValueError("无法在交付物中定位声明 %s，拒绝生成未落实核验结论的终稿" % claim["claim_id"])

        final_pages = [{key: page.get(key) for key in ("page_id", "title", "on_slide_text", "speaker_notes", "evidence_ids")} for page in pages]
        output = {
            "delivery_version": "P9-deterministic-1.0", "evidence_version": str(evidence_version),
            "final_report": {"title": report.get("report_title", "调研报告"), "markdown": markdown, "used_evidence_ids": list(report.get("used_evidence_ids", evidence_ids))},
            "final_ppt": {"deck_title": ppt.get("deck_title", "调研汇报"), "storyline": ppt.get("storyline", "证据驱动的研究综述"), "pages": final_pages},
            "verification_note": "已按独立核验结果确定性应用保留、降级、删除和未核实标记。",
            "open_issues": list(dict.fromkeys(item for item in open_issues if item)),
            "source_ids": list(source_ids), "evidence_ids": list(evidence_ids), "change_log": change_log,
        }
        return validate_final(output, claim_ids, source_ids, evidence_ids, verification), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}

    def extract_claims(self, report, ppt, evidence_ids, tier):
        report_chunks = self._text_chunks(report.get("report_markdown", ""))
        batches = []
        for index, chunk in enumerate(report_chunks, 1):
            partial_report = dict(report)
            partial_report["report_markdown"] = chunk
            label = "report" if len(report_chunks) == 1 else "report_part_%d_%d" % (index, len(report_chunks))
            batches.append((partial_report, {"deck_title": ppt.get("deck_title", ""), "storyline": "", "pages": []}, label))
        pages = ppt.get("pages", [])
        for index, page in enumerate(pages, 1):
            label = "ppt_page_%d" % index
            batches.append(({}, {"deck_title": ppt.get("deck_title", ""), "storyline": ppt.get("storyline", ""), "pages": [page]}, label))
        merged_claims, merged_notes = [], []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}

        def validate_batch(value):
            checked = validate_claims(value, evidence_ids)
            if len(checked["claims"]) > self.CLAIMS_PER_BATCH_LIMIT:
                raise ValueError("单批声明超过 %d 条上限" % self.CLAIMS_PER_BATCH_LIMIT)
            return checked

        for batch_report, batch_ppt, label in batches:
            partial, partial_usage, _ = self.generate(
                "P7", tier,
                {"report": batch_report, "ppt_package": batch_ppt, "evidence_ids": evidence_ids, "batch_label": label, "output_contract": load_contract("P7")},
                validate_batch, max_tokens=4000, max_attempts=3,
            )
            merged_claims.extend(partial["claims"])
            merged_notes.extend("%s: %s" % (label, note) for note in partial["extraction_notes"])
            add_usage(usage, partial_usage)
        for index, claim in enumerate(merged_claims, 1):
            claim["claim_id"] = "CLM-%04d" % index
        output = {"claim_set_version": "P7-batched-1.0", "claims": merged_claims, "extraction_notes": merged_notes}
        validate_claims(output, evidence_ids)
        return output, usage, {"batches": len(batches)}

    def verify_claims(self, claims, evidence_records, source_records, tier):
        claim_items = [item for item in claims.get("claims", []) if isinstance(item, dict)]
        if not claim_items:
            raise ValueError("独立核验至少需要 1 条声明")
        claim_ids = [item.get("claim_id") for item in claim_items]
        if any(not claim_id for claim_id in claim_ids) or len(claim_ids) != len(set(claim_ids)):
            raise ValueError("独立核验声明编号缺失或重复")
        evidence_ids = [item.get("evidence_id") for item in evidence_records if isinstance(item, dict)]
        if len(evidence_ids) != len(evidence_records) or any(not evidence_id for evidence_id in evidence_ids):
            raise ValueError("独立核验证据编号无效")
        evidence_by_id = {item["evidence_id"]: item for item in evidence_records}
        source_by_id = {item.get("source_id"): item for item in source_records if isinstance(item, dict) and item.get("source_id")}
        groups = {}
        for claim in claim_items:
            normalized = re.sub(r"\s+", "", claim.get("atomic_claim", "")).strip("。；;，,")
            key = (normalized, tuple(sorted(claim.get("cited_evidence_ids", []))))
            groups.setdefault(key, []).append(claim)
        representatives = [items[0] for items in groups.values()]
        representative_to_group = {items[0]["claim_id"]: items for items in groups.values()}
        representative_results = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}
        strong_types = {"causal", "efficacy", "safety", "approval"}
        strong = [item for item in representatives if item.get("claim_type") in strong_types and item.get("risk_level") in ("medium", "high")]
        standard = [item for item in representatives if item not in strong]
        routes = []
        for batch_group, upgrade, label in ((standard, False, "standard"), (strong, True, "high_risk")):
            for batch_items in self._verification_batches(batch_group, evidence_by_id, upgrade):
                batch_ids = [item["claim_id"] for item in batch_items]
                cited_ids = {evidence_id for item in batch_items for evidence_id in item.get("cited_evidence_ids", [])}
                batch_evidence = [evidence_by_id[evidence_id] for evidence_id in cited_ids if evidence_id in evidence_by_id]
                source_ids = {item.get("source_id") for item in batch_evidence}
                batch_sources = [source_by_id[source_id] for source_id in source_ids if source_id in source_by_id]
                output_limit = self._verification_output_limit(batch_items, evidence_by_id, upgrade)
                partial, partial_usage, route = self.generate(
                    "P8", tier,
                    {"claims": {"claim_set_version": claims.get("claim_set_version", ""), "claims": batch_items, "extraction_notes": []}, "evidence_records": batch_evidence, "source_records": batch_sources, "output_contract": load_contract("P8")},
                    lambda value, ids=batch_ids, items=batch_items: validate_verification(value, ids, evidence_ids, items),
                    upgrade=upgrade, max_tokens=output_limit, max_attempts=2, request_timeout=90,
                )
                representative_results.extend(partial["results"])
                add_usage(usage, partial_usage)
                routes.append({"class": label, "model": route["model"], "claims": len(batch_items), "evidence": len(batch_evidence), "max_output_tokens": output_limit})
        results = []
        for result in representative_results:
            for claim in representative_to_group[result["claim_id"]]:
                mapped = dict(result)
                mapped["claim_id"] = claim["claim_id"]
                results.append(mapped)
        result_order = {claim_id: index for index, claim_id in enumerate(claim_ids)}
        results.sort(key=lambda item: result_order[item["claim_id"]])
        summary = {status: sum(item["support_status"] == status for item in results) for status in ("supported", "partially_supported", "unsupported", "cannot_determine")}
        summary["high_risk_remaining"] = 0
        output = {"verification_version": "P8-batched-1.0", "results": results, "summary": summary}
        validate_verification(output, claim_ids, evidence_ids, claim_items)
        metadata = {
            "models": sorted({item["model"] for item in routes}), "reason": "risk_split",
            "batches": len(routes), "standard_claims": len(standard), "high_risk_claims": len(strong),
            "claims": len(claim_items), "unique_claims": len(representatives), "routes": routes,
        }
        return output, usage, metadata
