"""Application service that binds stages to prompts, routes, and model calls."""

import copy
import hashlib
import json
import math
import os
import re
import threading
import uuid
from pathlib import Path

from contracts import load_contract, validate_stage_output
from model_client import deepseek_json
from model_usage import ModelBudgetExceeded, ModelUsageLedger
from report_citations import render_linked_report
from reviewed_page_revisions import apply_reviewed_page_revisions
from ppt_boundary_repair import repair_verified_pages
from workflow_validation import (
    PPT_DENSITY_LIMITS,
    validate_claims, validate_evidence, validate_final, validate_intent, validate_plan,
    validate_ppt, validate_report, validate_screen, validate_verification,
)


def add_usage(total, partial):
    for key in total:
        total[key] += int(partial.get(key, 0) or 0)


class WorkflowService:
    CLAIMS_PER_BATCH_LIMIT = 6
    PRE_AUTH_INTENT_REQUEST_MAX_COST_CNY = 0.50
    def __init__(self, api_key, model_router, system_prompt, stage_prompts, model_client=deepseek_json, usage_ledger=None, model_limits=None, response_cache_dir=None, daily_budget_ledger=None):
        self.api_key = api_key
        self.model_router = model_router
        self.system_prompt = system_prompt
        self.stage_prompts = dict(stage_prompts)
        self.model_client = model_client
        self.usage_ledger = usage_ledger
        self.daily_budget_ledger = daily_budget_ledger
        self.model_limits = model_limits or {}
        self.response_cache_dir = Path(response_cache_dir) if response_cache_dir else None
        if self.response_cache_dir:
            self.response_cache_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.response_cache_dir, 0o700)
        self._context = threading.local()

    @classmethod
    def from_project(cls, api_key, model_router, root, model_client=deepseek_json, usage_ledger=None, model_limits=None, daily_budget_ledger=None):
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
        # The deployed SCF package is read-only; only /tmp is writable at runtime.
        # Keep the local-project default for development, while allowing SCF to
        # override it explicitly and avoid writing under the deployment bundle.
        cache_dir = os.environ.get("SCF_RESPONSE_CACHE_DIR")
        if not cache_dir:
            # Tencent SCF exposes a writable /tmp even when its runtime marker
            # variables are absent. Never fall back to the read-only source tree.
            cloud_runtime = (
                os.environ.get("SCF_RUNTIME")
                or os.environ.get("TENCENTCLOUD_RUNENV")
                or str(root).startswith("/var/user/")
            )
            cache_dir = "/tmp/model-response-cache" if cloud_runtime else str(root / "data" / "private" / "model-response-cache")
        return cls(api_key, model_router, system_prompt, stage_prompts, model_client, usage_ledger, model_limits, cache_dir, daily_budget_ledger)

    def set_task_context(self, task_id):
        self._context.task_id = task_id

    @staticmethod
    def enforce_current_citation(result, claim):
        """Fail closed when the model supports a claim only with a different citation."""
        cited = set(claim.get("cited_evidence_ids", []))
        valid = set(result.get("valid_evidence_ids", []))
        if result.get("support_status") not in ("supported", "partially_supported") or cited.intersection(valid):
            return result
        checked = dict(result)
        if cited:
            checked.update({
                "support_status": "unsupported", "action": "remove", "revised_claim": None,
                "valid_evidence_ids": [], "issue_codes": ["source_mismatch", "citation_missing"],
                "explanation": "当前声明绑定的证据编号不支持该结论；同源其他证据只能作为改正建议，原引用按不支持处理。 " + result.get("explanation", ""),
            })
        else:
            checked.update({
                "support_status": "cannot_determine", "action": "mark_unverified",
                "valid_evidence_ids": [], "issue_codes": ["citation_missing", "evidence_missing"],
                "revised_claim": result.get("revised_claim") or claim.get("atomic_claim"),
                "explanation": "当前声明没有绑定可核验的证据编号；其他证据只能作为补引建议，原声明先标记未核实。 " + result.get("explanation", ""),
            })
        return checked

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
        ceiling = 9600 if upgrade else 3800
        floor = 6400 if upgrade else 1200
        multiplier = 2 if upgrade else 1
        return min(ceiling, max(floor, multiplier * (650 + len(items) * 220 + complexity * 70)))

    def generate(self, stage, tier, payload, validator=None, *, upgrade=False, max_tokens=6000, max_attempts=2, request_timeout=300, request_cost_limit_cny=None, daily_budget_request_id=None):
        if stage not in self.stage_prompts:
            raise ValueError("阶段 %s 缺少提示词" % stage)
        route = self.model_router.for_stage(stage, tier, upgrade=upgrade)
        task_id = getattr(self._context, "task_id", "unassigned")
        usage_request_id = str(uuid.uuid4())
        usage_task_id = ("PREAUTH-" + usage_request_id) if stage == "P1" else task_id
        usage_limits = dict(self.model_limits)
        if request_cost_limit_cny is not None:
            current_limit = float(usage_limits.get("task_max_cost_cny", 0) or 0)
            usage_limits["task_max_cost_cny"] = min(current_limit, float(request_cost_limit_cny)) if current_limit else float(request_cost_limit_cny)
        input_text = self.system_prompt + self.stage_prompts[stage] + json.dumps(payload, ensure_ascii=False)
        # The budget guard accepts token counts, not UTF-8 byte counts. Chinese
        # text commonly occupies three bytes per character, so passing bytes
        # directly can over-reserve by roughly 3x and stop a valid task late in
        # a multi-batch stage. Two bytes per estimated token remains deliberately
        # conservative for mixed Chinese/English research payloads.
        estimated_input_tokens = max(1, math.ceil(len(input_text.encode("utf-8")) / 2))

        cache_path = None
        if self.response_cache_dir and task_id != "unassigned":
            cache_key = hashlib.sha256(json.dumps({
                "task_id": task_id, "stage": stage, "tier": tier, "upgrade": upgrade,
                "model": route["model"], "effort": route["effort"], "prompt": self.stage_prompts[stage],
                "payload": payload,
            }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            cache_path = self.response_cache_dir / (cache_key + ".json")
            if cache_path.is_file():
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                try:
                    output = validator(cached["output"]) if validator else cached["output"]
                except ValueError as exc:
                    if self.usage_ledger:
                        self.usage_ledger.record(task_id, stage, route["model"], route["effort"], 0, "cache_rejected", {}, {"cache_key": cache_key, "reason": str(exc)[:160]})
                else:
                    if self.usage_ledger:
                        self.usage_ledger.record(task_id, stage, route["model"], route["effort"], 0, "cache_hit", {}, {"cache_key": cache_key})
                    return output, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}, route

        attempt_reservations = {}

        def record(attempt, status, usage, detail):
            if request_cost_limit_cny is not None:
                prompt_tokens = int((usage or {}).get("prompt_tokens", 0) or 0)
                output_tokens = int((usage or {}).get("completion_tokens", 0) or 0)
                if prompt_tokens or output_tokens:
                    # Never release the conservative reservation when actual usage is higher.
                    attempt_reservations[attempt] = max(
                        attempt_reservations.get(attempt, 0.0),
                        ModelUsageLedger.estimate_peak_cost_cny(route["model"], prompt_tokens, output_tokens),
                    )
            if self.usage_ledger:
                record_attempt = getattr(self.usage_ledger, "record_attempt", None)
                if callable(record_attempt):
                    record_attempt(usage_task_id, usage_request_id, attempt, status, usage, detail)
                else:
                    self.usage_ledger.record(task_id, stage, route["model"], route["effort"], attempt, status, usage, detail)
            if self.daily_budget_ledger and stage == "P1" and attempt in attempt_reservations:
                known_usage = bool(
                    int((usage or {}).get("prompt_tokens", 0) or 0)
                    or int((usage or {}).get("completion_tokens", 0) or 0)
                )
                detail = detail if isinstance(detail, dict) else {}
                response_status = detail.get("status")
                explicitly_rejected = (
                    status == "http_error"
                    and isinstance(response_status, int)
                    and 400 <= response_status < 500
                )
                actual_cost = 0 if explicitly_rejected else (
                    ModelUsageLedger.estimate_peak_cost_cny(
                        route["model"],
                        int((usage or {}).get("prompt_tokens", 0) or 0),
                        int((usage or {}).get("completion_tokens", 0) or 0),
                    ) if known_usage else None
                )
                self.daily_budget_ledger.settle_attempt(
                    daily_budget_request_id, attempt, actual_cost,
                )

        def guard(attempt):
            if request_cost_limit_cny is not None:
                # Leave room for token-estimation variance and the validation-retry suffix.
                # For pre-auth P1, UTF-8 byte count is a conservative token
                # upper bound (at least one input byte per tokenizer token).
                # Add 2048 tokens for message framing and the bounded retry suffix.
                reserved_input_tokens = (
                    len(input_text.encode("utf-8")) + 2048
                    if stage == "P1" and request_cost_limit_cny is not None
                    else math.ceil(estimated_input_tokens * 1.25) + 256
                )
                next_attempt_cost = ModelUsageLedger.estimate_peak_cost_cny(
                    route["model"], reserved_input_tokens, max_tokens,
                )
                already_reserved = sum(attempt_reservations.values())
                if already_reserved + next_attempt_cost > float(request_cost_limit_cny):
                    raise ModelBudgetExceeded(
                        "登录前意图识别达到单次费用上限 %.2f 元，已停止后续模型调用"
                        % float(request_cost_limit_cny)
                    )
                attempt_reservations[attempt] = next_attempt_cost
            if self.usage_ledger:
                reserve_attempt = getattr(self.usage_ledger, "reserve_attempt", None)
                if callable(reserve_attempt):
                    reserve_attempt(
                        usage_task_id, usage_request_id, attempt, stage, route["model"],
                        route["effort"], usage_limits, estimated_input_tokens, max_tokens,
                    )
                else:
                    self.usage_ledger.guard(task_id, route["model"], usage_limits, max_tokens, estimated_input_tokens)
            if self.daily_budget_ledger and stage == "P1":
                if not daily_budget_request_id:
                    raise ModelBudgetExceeded("登录前每日预算缺少请求标识，已拒绝模型调用")
                self.daily_budget_ledger.reserve_attempt(
                    daily_budget_request_id, attempt, next_attempt_cost,
                )
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
        if cache_path:
            temporary = cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"output": output}, ensure_ascii=False), encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(cache_path)
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

    def create_intent(self, topic, tier="fast", *, request_timeout=300):
        topic = str(topic or "").strip()
        tier = self._tier(tier)
        if not 2 <= len(topic) <= 500:
            raise ValueError("请输入 2—500 字的主题并选择有效版本")
        output, usage, _ = self.generate(
            "P1", tier, {"topic": topic, "tier": tier, "runtime_config": {"language": "zh-CN"}},
            validate_intent, max_tokens=4200, max_attempts=2,
            request_timeout=request_timeout,
            request_cost_limit_cny=self.PRE_AUTH_INTENT_REQUEST_MAX_COST_CNY,
            daily_budget_request_id=str(uuid.uuid4()) if self.daily_budget_ledger else None,
        )
        return output, usage

    def create_plan(self, topic, clarification="", tier="fast", intent=None):
        topic = str(topic or "").strip()
        clarification = str(clarification or "").strip()
        tier = self._tier(tier)
        if not 2 <= len(topic) <= 500:
            raise ValueError("规划输入无效")
        normalized = topic + (("；用户澄清：" + clarification) if clarification else "")
        if intent is not None and not isinstance(intent, dict):
            raise ValueError("规划意图输入无效")
        planning_intent = dict(intent or {"domain": "life_science", "normalized_topic": normalized, "tier": tier, "need_clarification": False})
        planning_intent["normalized_topic"] = normalized
        planning_intent["tier"] = tier
        planning_intent["need_clarification"] = False
        def validate_blueprint_output(value):
            # Explanatory keys inside an otherwise valid retrieval task are
            # harmless and unused downstream. Strip them locally instead of
            # paying for a second complete Pro generation.
            if isinstance(value, dict) and isinstance(value.get("questions"), list):
                allowed = {"question_id", "question", "evidence_needs"}
                value["questions"] = [
                    {key: item[key] for key in allowed if key in item}
                    if isinstance(item, dict) else item
                    for item in value["questions"]
                ]
            return validate_stage_output("P2B", value)

        architecture, architecture_usage, _ = self.generate(
            "P2A", tier, {
                "intent": planning_intent,
                "tier": tier,
                "output_contract": load_contract("P2A"),
            }, lambda value: validate_stage_output("P2A", value),
            # P2A uses a reasoning model, and hidden reasoning shares this
            # allowance with the visible JSON. A 2,800-token demo request used
            # 2,541 tokens on reasoning alone and truncated the plan. Keep one
            # explicit 10K ceiling for both tiers so live demonstrations do not
            # fail merely because the reasoning/output split varies.
            max_tokens=4200, max_attempts=2,
        )
        blueprint, blueprint_usage, _ = self.generate(
            "P2B", tier, {
                "intent": planning_intent,
                "research_architecture": architecture,
                "available_sources": ["PubMed", "Europe PMC", "Crossref"]
                + (["智慧芽 MCP 专利"] if os.environ.get("PATSNAP_MCP_API_KEY", "").strip() else ["EPO OPS"])
                + (["Patsnap"] if os.environ.get("PATSNAP_API_KEY", "").strip() else []) + ["official"],
                "runtime_config": {"source_limit": 19 if tier == "deep" else 10, "language": "zh-CN"},
                "output_contract": load_contract("P2B"),
            }, validate_blueprint_output,
            # Reasoning tokens share the response cap with the JSON body. The
            # previous 4400-token cap truncated two paid Pro responses here.
            # P2B uses a lower-cost synthesis route after P2A establishes the
            # research framing; retain enough output room for the full plan.
            max_tokens=7500, max_attempts=2,
        )
        output = {
            "research_scope": architecture["research_scope"],
            "exclusions": architecture["exclusions"],
            "questions": blueprint["questions"],
            "search_concepts": blueprint["search_concepts"],
            "source_plan": blueprint["source_plan"],
            "selection_criteria": blueprint["selection_criteria"],
            "stop_conditions": blueprint["stop_conditions"],
            "report_outline": blueprint["report_outline"],
            "ppt_story_arc": blueprint["ppt_story_arc"],
            "risks": list(dict.fromkeys(architecture["risks"] + blueprint["risks"])),
        }
        validate_plan(output)
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}
        add_usage(usage, architecture_usage)
        add_usage(usage, blueprint_usage)
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
        keys = ("source_id", "source", "title", "abstract", "year", "access", "url",
                "canonical_identity", "source_type", "publication_level", "independence_group",
                "reading_scope", "retrieved_at", "intended_uses", "also_found_in")
        compact = [{key: item.get(key) for key in keys} for item in candidates]
        compact_plan = {key: plan.get(key) for key in ("research_scope", "questions", "source_plan", "selection_criteria")}
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}
        decisions, open_issues = [], []
        for offset in range(0, len(compact), 4):
            batch = compact[offset:offset + 4]
            batch_ids = [item["source_id"] for item in batch]

            def validate_screen_batch(value, ids=batch_ids):
                # Explanatory prose occasionally arrives in this harmless
                # top-level field, and models may echo candidate metadata into
                # a decision. Dropping unused echoes is deterministic and
                # avoids a paid retry without changing any screening decision.
                if isinstance(value, dict):
                    value.pop("screening_notes", None)
                    decision_keys = {
                        "source_id", "status", "question_ids", "intended_uses",
                        "reason", "priority", "relevance_score", "evidence_type", "flags",
                    }
                    if isinstance(value.get("decisions"), list):
                        value["decisions"] = [
                            {key: item[key] for key in decision_keys if key in item}
                            if isinstance(item, dict) else item
                            for item in value["decisions"]
                        ]
                return validate_screen(value, ids, len(ids))

            partial, partial_usage, _ = self.generate(
                "P3", tier,
                {"topic": topic, "plan": compact_plan, "candidate_sources": batch, "limits": {"keep_max": len(batch), "tier": tier}, "output_contract": load_contract("P3")},
                validate_screen_batch, max_tokens=2100, max_attempts=2,
            )
            decision_keys = {
                "source_id", "status", "question_ids", "intended_uses",
                "reason", "priority", "relevance_score", "evidence_type", "flags",
            }
            partial["decisions"] = [
                {key: item[key] for key in decision_keys if key in item}
                for item in partial["decisions"]
            ]
            decisions.extend(partial["decisions"])
            open_issues.extend(partial["summary"].get("open_issues", []))
            add_usage(usage, partial_usage)
        kept = sorted((item for item in decisions if item["status"] == "keep"), key=lambda item: (item.get("relevance_score", 0), item.get("priority") == "high"), reverse=True)
        for item in kept[keep_max:]:
            item["status"] = "reserve"
            item["reason"] = (item.get("reason", "") + " 全局保留上限由程序降为备选。").strip()
        output = {"screening_version": "P3-batched-1.0", "topic": topic, "decisions": decisions, "summary": {"candidate_count": len(candidate_ids), "keep_count": 0, "reserve_count": 0, "drop_count": 0, "open_issues": list(dict.fromkeys(open_issues))}}
        return validate_screen(output, candidate_ids, keep_max), usage

    def extract_evidence(self, source_record, question_ids, tier="fast"):
        tier = self._tier(tier)
        if not isinstance(source_record, dict) or not isinstance(question_ids, list):
            raise ValueError("证据提取输入无效")
        source_id = str(source_record.get("source_id", "")).strip()
        source_text = str(source_record.get("full_text") or source_record.get("abstract", "")).strip()
        if not source_id:
            raise ValueError("来源缺少 source_id")
        if not source_text:
            output = {"evidence_version": "1.0", "source_id": source_id, "extraction_status": "no_extractable_evidence", "reading_scope": "metadata_only", "evidence_records": [], "figure_records": [], "no_extractable_reason": "当前来源没有可读取摘要或正文"}
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}
            return validate_evidence(output, source_id, source_record.get("access")), usage
        keys = ("source_id", "source", "title", "authors", "journal", "year", "url", "access", "pmcid")
        compact = {key: source_record.get(key) for key in keys}
        allowed_figure_ids = [item.get("figure_id") for item in source_record.get("figure_candidates", []) if item.get("figure_id")]
        # Full-text evidence includes conditions, limitations and original
        # multi-panel captions; the abstract-sized cap truncated valid JSON.
        output_limit = 8000 if source_record.get("full_text") else 4500
        output, usage, _ = self.generate(
            "P4", tier,
            {"source_record": compact, "source_text": source_text, "figure_candidates": source_record.get("figure_candidates", []), "question_ids": question_ids, "limits": {"evidence_records_max": 8, "figure_records_max": 4}, "output_contract": load_contract("P4")},
            lambda value: validate_evidence(value, source_id, source_record.get("access"), allowed_figure_ids, 8, 4), max_tokens=output_limit, max_attempts=2,
        )
        # Each source is extracted independently, so model-local EV-001 style IDs
        # are not globally unique. Namespace them deterministically before they
        # can be merged into a report task.
        for index, evidence in enumerate(output["evidence_records"], 1):
            evidence["evidence_id"] = "EV::%s::%03d" % (source_id, index)
        candidates_by_id = {item.get("figure_id"): item for item in source_record.get("figure_candidates", [])}
        for figure in output["figure_records"]:
            candidate = candidates_by_id.get(figure["figure_id"], {})
            if candidate.get("caption"):
                figure["caption"] = candidate["caption"]
            figure_url = str(candidate.get("article_figure_url") or "").strip()
            # A model may describe why a figure is useful, but cannot grant
            # reuse rights or invent its authoritative source location.
            figure["reuse_status"] = candidate.get("reuse_status", "unknown")
            if candidate.get("label"):
                figure["label"] = candidate["label"]
            if figure_url and figure_url not in figure["locator"]:
                figure["locator"] = "%s | %s" % (figure["locator"], figure_url)
            if figure_url:
                figure["article_figure_url"] = figure_url
        return output, usage

    def create_report(self, intent, plan, evidence_records, tier="fast", evidence_contexts=None, figure_records=None):
        tier = self._tier(tier)
        figure_records = [] if figure_records is None else figure_records
        if not isinstance(intent, dict) or not isinstance(plan, dict) or not isinstance(evidence_records, list) or not isinstance(figure_records, list):
            raise ValueError("报告生成输入无效")
        if not 1 <= len(evidence_records) <= 100:
            raise ValueError("至少需要 1 条且最多处理 100 条证据")
        evidence_ids = self._ids(evidence_records, "evidence_id", "证据编号缺失或重复")
        figure_ids = set(self._ids(figure_records, "figure_id", "报告输入包含无效图片编号"))
        figure_by_id = {item["figure_id"]: item for item in figure_records}
        def validate_report_output(value):
            if isinstance(value, dict):
                report_keys = {
                    "report_version", "report_title", "report_markdown",
                    "used_evidence_ids", "figure_recommendations", "status", "open_issues",
                }
                value = {key: item for key, item in value.items() if key in report_keys}
            validated = validate_report(value, evidence_ids, tier)
            for recommendation in validated["figure_recommendations"]:
                figure = figure_by_id.get(recommendation["figure_id"])
                if recommendation["figure_id"] not in figure_ids or recommendation["reuse_status"] != figure["reuse_status"]:
                    raise ValueError("P5 推荐了未提供的图片或改写了图片复用状态")
            return validated

        output, usage, _ = self.generate(
            "P5", tier,
            {"intent": intent, "plan": plan, "evidence_records": evidence_records, "evidence_contexts": evidence_contexts or [], "figure_records": figure_records, "tier": tier, "output_contract": load_contract("P5")},
            # Deep reports can include many source-bound evidence records; the
            # former 7,500 cap truncated complete drafts. Give only this stage
            # enough room, while the request-time task budget remains enforced.
            validate_report_output, max_tokens=10000, max_attempts=2,
        )
        return output, usage

    def create_ppt(self, intent, report, evidence_records, figure_records=None, constraints=None, tier="fast", plan=None, source_records=None):
        tier = self._tier(tier)
        figure_records = [] if figure_records is None else figure_records
        constraints = {} if constraints is None else constraints
        source_records = [] if source_records is None else source_records
        if not isinstance(intent, dict) or not isinstance(report, dict) or not isinstance(evidence_records, list) or not isinstance(figure_records, list) or not isinstance(source_records, list) or not isinstance(constraints, dict) or (plan is not None and not isinstance(plan, dict)):
            raise ValueError("PPT 内容包输入无效")
        all_evidence_ids = self._ids(evidence_records, "evidence_id", "PPT 输入包含无效证据编号", unique=False)
        report_text = str(report.get("report_markdown") or "")
        cited_in_report = set(re.findall(r"EV::.+?::\d{3}", report_text))
        report_evidence_ids = [item for item in all_evidence_ids if item in cited_in_report]
        # The deck may only draw evidence already cited by the validated report.
        # This both narrows the model's choices and prevents unsupported IDs
        # from entering the customer-facing storyboard.
        evidence_ids = report_evidence_ids or all_evidence_ids
        allowed_evidence = set(evidence_ids)
        evidence_records = [item for item in evidence_records if item.get("evidence_id") in allowed_evidence]
        figure_ids = self._ids(figure_records, "figure_id", "PPT 输入包含无效图片编号", unique=False)
        source_ids = self._ids(source_records, "source_id", "PPT 输入包含无效来源编号", unique=False)
        payload = {"intent": intent, "plan": plan or {}, "report": report, "evidence_records": evidence_records,
                   "figure_records": figure_records, "source_records": source_records,
                   "allowed_evidence_ids": evidence_ids, "allowed_figure_ids": figure_ids,
                   "allowed_source_ids": source_ids, "presentation_limits": PPT_DENSITY_LIMITS,
                   "constraints": constraints, "output_contract": load_contract("P6")}

        def generate_ppt_batch(batch_payload, token_limit, validator):
            try:
                return self.generate("P6", tier, batch_payload, validator,
                                     max_tokens=token_limit, max_attempts=1)
            except ValueError as exc:
                message = str(exc)
                if "P6 页面使用了不存在的 evidence_id" not in message:
                    raise
                corrected_payload = dict(batch_payload)
                corrected_payload["validation_feedback"] = (
                    "上次页面因证据编号不在 allowed_evidence_ids 白名单而被拒绝。"
                    "只可逐字使用白名单中的编号；若某条判断没有可用编号，应删除或收窄该判断，不得自造编号。"
                    "校验信息：" + message[:400]
                )
                return self.generate("P6", tier, corrected_payload, validator,
                                     max_tokens=token_limit, max_attempts=1)

        arc = (plan or {}).get("ppt_story_arc", [])
        split_long_report = tier == "deep" and len(str(report.get("report_markdown") or "")) > 7000 and len(arc) >= 4
        if split_long_report:
            midpoint = (len(arc) + 1) // 2
            parts = []
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}
            for index, subset in enumerate((arc[:midpoint], arc[midpoint:]), 1):
                batch_payload = {**payload, "page_batch": {"index": index, "total": 2,
                    "assigned_arc": subset, "target_pages": "4—6", "complete_arc": arc}}
                partial, partial_usage, _ = generate_ppt_batch(
                    batch_payload, 7000,
                    lambda value: validate_ppt(value, evidence_ids, figure_ids, source_ids),
                )
                parts.append(partial)
                add_usage(usage, partial_usage)
            output = {"deck_title": parts[0]["deck_title"], "storyline": parts[0]["storyline"],
                      "pages": [page for part in parts for page in part["pages"]]}
            for index, page in enumerate(output["pages"], 1):
                page["page_id"] = "SL-%02d" % index
            validate_ppt(output, evidence_ids, figure_ids, source_ids)
        else:
            output, usage, _ = generate_ppt_batch(
                payload, 9000,
                lambda value: validate_ppt(value, evidence_ids, figure_ids, source_ids),
            )
        figure_by_id = {item.get("figure_id"): item for item in figure_records}
        for page in output["pages"]:
            for reference in page["figure_refs"]:
                figure = figure_by_id[reference["figure_id"]]
                reference["source_id"] = figure["source_id"]
                reference["locator"] = figure["locator"]
                reference["reuse_status"] = figure["reuse_status"]
            page["figure_refs"] = [
                reference for reference in page["figure_refs"]
                if re.search(r"https://[^\s|;，,）)]+", str(reference.get("locator", "")))
            ]
            if not page["figure_refs"]:
                page["visual_suggestion"] = ""
            for citation in page["source_citations"]:
                citation["short_vancouver"] = citation["short_vancouver"].replace(" 信息不完。", "").replace(" 信息不完整。", "")
        return output, usage

    @staticmethod
    def _short_vancouver(source):
        authors = source.get("authors") or []
        first = str(authors[0]).strip() if authors else "Unknown author"
        author_text = first + (", et al." if len(authors) > 1 else ".")
        journal = str(source.get("journal") or source.get("source") or "Unknown journal").strip()
        year = str(source.get("year") or "n.d.").strip()
        volume = str(source.get("volume") or "").strip()
        issue = str(source.get("issue") or "").strip()
        pages = str(source.get("pages") or "").strip()
        locator = volume + (("(" + issue + ")") if issue else "")
        if pages:
            locator += (":" if locator else "") + pages
        return "%s %s. %s%s." % (author_text, journal, year, (";" + locator) if locator else "")

    def assemble_final(self, verification, report, ppt, claim_ids, source_ids, evidence_ids, evidence_version="1.0", tier="fast"):
        tier = self._tier(tier)
        if not all(isinstance(item, list) for item in (claim_ids, source_ids, evidence_ids)) or not all(isinstance(item, dict) for item in (verification, report, ppt)):
            raise ValueError("最终装配输入无效")
        output, usage, _ = self.generate(
            "P9", tier,
            {"verification_results": verification, "draft_report": report, "draft_ppt": ppt, "claim_ids": claim_ids, "source_ids": source_ids, "evidence_ids": evidence_ids, "evidence_version": str(evidence_version), "output_contract": load_contract("P9")},
            lambda value: validate_final(value, claim_ids, source_ids, evidence_ids, verification), max_tokens=12000, max_attempts=3,
        )
        for page in output.get("final_ppt", {}).get("pages", []):
            page["figure_refs"] = [
                ref for ref in page.get("figure_refs", [])
                if re.search(r"https://[^\s|;，,）)]+", str(ref.get("locator", "")))
            ]
            if not page["figure_refs"]:
                page["visual_suggestion"] = ""
        return output, usage

    def assemble_final_deterministic(self, verification, report, ppt, claims, source_ids, evidence_ids, evidence_version="1.0", evidence_records=None, source_records=None, figure_records=None, reviewed_page_edits=None):
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
        overflow_revisions = []
        resolved_page_claim_text = {}
        action_names = {"keep": "kept", "revise": "revised", "remove": "removed", "mark_unverified": "marked_unverified"}

        def replace_once(text, original, replacement):
            candidates = [original, original.rstrip("。；;，,"), original.strip()]
            # P7 may normalize a well-known gene symbol to its protein name
            # while copying the rest of the sentence exactly. Treat only this
            # explicit alias as equivalent; do not fall back to replacing the
            # whole surrounding sentence, which can contain other claims.
            aliases = (("Claudin18.2", "CLDN18.2"), ("CLDN18.2", "Claudin18.2"))
            for source, target in aliases:
                if source in original:
                    candidates.append(original.replace(source, target))
            if "：" in original and len(original.rsplit("：", 1)[-1].strip()) >= 6:
                candidates.append(original.rsplit("：", 1)[-1].strip().rstrip("。；;，,"))
            for candidate in dict.fromkeys(item for item in candidates if item):
                if candidate in text:
                    return text.replace(candidate, replacement, 1), True
            return text, False

        def replace_unique_similar_sentence(text, original, replacement):
            """Repair punctuation/alias drift without guessing among matches."""
            def normalized(value):
                return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff%]+", "", str(value)).lower()

            target = normalized(original)
            target_bigrams = {target[index:index + 2] for index in range(max(0, len(target) - 1))}
            if len(target_bigrams) < 8:
                return text, False
            candidates = []
            for match in re.finditer(r"[^\n。！？!?]+[。！？!?]?", text):
                sentence = match.group(0)
                current = normalized(sentence)
                if not current:
                    continue
                coverage = sum(item in current for item in target_bigrams) / len(target_bigrams)
                if coverage >= 0.72:
                    candidates.append((coverage, match.start(), match.end(), sentence))
            candidates.sort(reverse=True)
            if not candidates or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.08):
                return text, False
            _, start, end, sentence = candidates[0]
            trailing = sentence[-1] if sentence and sentence[-1] in "。！？!?" and replacement else ""
            return text[:start] + replacement.rstrip("。！？!?") + trailing + text[end:], True

        def append_verification_note(page, claim_id, replacement):
            note = replacement
            current = str(page.get("speaker_notes", "")).strip()
            candidate = (current + "\n" + note).strip()
            if len(candidate) > PPT_DENSITY_LIMITS["speaker_notes_max"]:
                return False
            page["speaker_notes"] = candidate
            return True

        def defer_page_revision(claim, replacement, result):
            overflow_revisions.append({
                "page_id": claim.get("section_or_page_id"),
                "claim_id": claim.get("claim_id"),
                "text": str(replacement or "").strip(),
                "evidence_ids": list(result.get("valid_evidence_ids", [])),
            })

        def unique_embedded_numeric_line(page, claim_text):
            """Locate one longer slide bullet that conservatively contains a numeric claim."""
            numeric_anchors = re.findall(r"(?:[IVX]+期|\d+(?:\.\d+)?%?)", claim_text)
            han = "".join(re.findall(r"[\u4e00-\u9fff]", claim_text))
            bigrams = {han[index:index + 2] for index in range(max(0, len(han) - 1))}
            if not numeric_anchors or len(bigrams) < 4:
                return None
            matches = []
            for index, line in enumerate(page.get("on_slide_text", [])):
                text = str(line)
                coverage = sum(item in text for item in bigrams) / len(bigrams)
                if all(anchor in text for anchor in numeric_anchors) and coverage >= 0.7:
                    matches.append(index)
            return matches[0] if len(matches) == 1 else None

        def slide_replacement(page, index, candidate, replacement, claim, result):
            other_characters = sum(len(str(line)) for position, line in enumerate(page.get("on_slide_text", [])) if position != index)
            if len(replacement) <= PPT_DENSITY_LIMITS["bullet_characters_max"] and len(candidate) <= PPT_DENSITY_LIMITS["bullet_characters_max"] and other_characters + len(candidate) <= PPT_DENSITY_LIMITS["page_characters_max"]:
                return candidate
            if append_verification_note(page, claim["claim_id"], replacement):
                return ""
            defer_page_revision(claim, replacement, result)
            return ""

        def replace_note_verification(page, claim, replacement, result):
            """Replace the exact note claim or defer the full revision intact."""
            notes = str(page.get("speaker_notes", ""))
            revised, located = replace_once(notes, claim["original_text"], replacement)
            atomic = str(claim.get("atomic_claim") or "").strip()
            if not located and atomic:
                revised, located = replace_once(notes, atomic, replacement)
            if not located:
                revised, located = replace_unique_similar_sentence(
                    notes, atomic or claim["original_text"], replacement
                )
            if not located:
                return False
            if len(revised) <= PPT_DENSITY_LIMITS["speaker_notes_max"]:
                page["speaker_notes"] = revised
            else:
                # Retain the original notes and put the complete verified
                # replacement on a supplementary page; never truncate it.
                defer_page_revision(claim, replacement, result)
            return True

        for claim in claims:
            result = results[claim["claim_id"]]
            action = result["action"]
            change_log.append({"claim_id": claim["claim_id"], "action": action_names[action], "reason": result["explanation"]})
            if action == "keep":
                continue
            claim_original_text = claim["original_text"]
            original = claim_original_text
            atomic = str(claim.get("atomic_claim") or "").strip()
            page = None
            if claim["location_type"] == "report_section":
                search_space = markdown
            else:
                search_page = pages_by_id.get(claim["section_or_page_id"], {})
                if claim["location_type"] == "ppt_speaker_note":
                    search_space = str(search_page.get("speaker_notes", ""))
                elif claim["location_type"] == "ppt_visual":
                    search_space = str(search_page.get("visual_suggestion", ""))
                elif claim["location_type"] == "ppt_slide":
                    search_space = "\n".join([
                        str(search_page.get("title", "")), str(search_page.get("purpose", "")),
                        "\n".join(search_page.get("on_slide_text", [])),
                    ])
                else:
                    search_space = "\n".join([
                        str(search_page.get("title", "")), str(search_page.get("purpose", "")),
                        "\n".join(search_page.get("on_slide_text", [])),
                        str(search_page.get("visual_suggestion", "")), str(search_page.get("speaker_notes", "")),
                    ])
            if original not in search_space and atomic and atomic.rstrip("。；;，,") in search_space:
                original = atomic
            replacement = result.get("revised_claim") or ""
            if action == "mark_unverified":
                if claim["location_type"] == "report_section":
                    # A customer report must not present an unsupported claim
                    # as a fact with a small audit label appended. Remove it
                    # from the prose and retain the issue for review instead.
                    issue = "尚待核实：" + (replacement or atomic or original).strip()
                    if claim["section_or_page_id"] not in ("open_issues",) and not claim["section_or_page_id"].startswith("open_issues_"):
                        if issue not in open_issues:
                            open_issues.append(issue)
                    replacement = ""
                else:
                    page_for_limit = pages_by_id.get(claim["section_or_page_id"], {})
                    page_context = str(page_for_limit.get("title", "")) + str(page_for_limit.get("purpose", ""))
                    if any(term in page_context for term in ("局限", "争议", "研究空白", "证据边界", "不足与展望")):
                        replacement = (replacement or original) + "（未核实）"
                    else:
                        replacement = ""
            located = False
            if claim["location_type"] == "report_section":
                markdown, located = replace_once(markdown, original, replacement)
                if not located:
                    markdown, located = replace_unique_similar_sentence(markdown, atomic or original, replacement)
                if not located and (
                    claim["section_or_page_id"] == "open_issues"
                    or claim["section_or_page_id"].startswith("open_issues_")
                ):
                    matching = [index for index, item in enumerate(open_issues) if str(item).strip() == str(original).strip()]
                    if len(matching) == 1:
                        open_issues[matching[0]] = issue if action == "mark_unverified" else replacement
                    else:
                        open_issues.append(issue if action == "mark_unverified" else replacement)
                    located = True
            else:
                page = pages_by_id.get(claim["section_or_page_id"])
                if page:
                    field = "speaker_notes" if claim["location_type"] == "ppt_speaker_note" else "visual_suggestion" if claim["location_type"] == "ppt_visual" else "on_slide_text"
                    if field == "speaker_notes":
                        located = replace_note_verification(page, claim, replacement, result)
                    elif field == "visual_suggestion":
                        page[field], located = replace_once(page.get(field, ""), original, replacement)
                        if not located:
                            page[field], located = replace_unique_similar_sentence(page.get(field, ""), atomic or original, replacement)
                    else:
                        for index, line in enumerate(page.get(field, [])):
                            candidate, located = replace_once(line, original, replacement)
                            if not located:
                                candidate, located = replace_unique_similar_sentence(line, atomic or original, replacement)
                            if located:
                                page[field][index] = slide_replacement(page, index, candidate, replacement, claim, result)
                                break
                        if not located and action == "remove" and claim["location_type"] == "ppt_slide":
                            embedded_index = unique_embedded_numeric_line(page, atomic or original)
                            if embedded_index is not None:
                                page["on_slide_text"].pop(embedded_index)
                                located = True
            if not located:
                if page and claim["location_type"].startswith("ppt_"):
                    # P7 can occasionally label the right page but the wrong
                    # customer-facing field. Recover only an exact, unique
                    # occurrence on that same page; never search other pages.
                    alternative_slide_matches = []
                    for index, line in enumerate(page.get("on_slide_text", [])):
                        for candidate_text in (original, atomic):
                            if candidate_text and candidate_text in str(line):
                                alternative_slide_matches.append((index, candidate_text))
                                break
                    if len(alternative_slide_matches) == 1:
                        index, candidate_text = alternative_slide_matches[0]
                        line = str(page["on_slide_text"][index])
                        revised_line = line.replace(candidate_text, replacement, 1)
                        page["on_slide_text"][index] = slide_replacement(
                            page, index, revised_line, replacement, claim, result
                        )
                        located = True
                    elif replacement:
                        visual = str(page.get("visual_suggestion", ""))
                        visual_match = next((item for item in (original, atomic) if item and item in visual), "")
                        if visual_match:
                            page["visual_suggestion"] = visual.replace(visual_match, "", 1).strip(" ，,；;")
                            if (len(replacement) <= PPT_DENSITY_LIMITS["bullet_characters_max"]
                                    and sum(len(str(line)) for line in page.get("on_slide_text", [])) + len(replacement)
                                    <= PPT_DENSITY_LIMITS["page_characters_max"]):
                                page.setdefault("on_slide_text", []).append(replacement)
                            elif not append_verification_note(page, claim["claim_id"], replacement):
                                defer_page_revision(claim, replacement, result)
                            located = True
                    page_text = "\n".join([
                        str(page.get("title", "")), str(page.get("purpose", "")),
                        "\n".join(page.get("on_slide_text", [])),
                        str(page.get("visual_suggestion", "")), str(page.get("speaker_notes", "")),
                    ])
                    if not located and replacement and replacement.strip() in page_text:
                        located = True
                    elif not located and action == "remove":
                        key = (claim["section_or_page_id"], claim["location_type"])
                        prior = resolved_page_claim_text.get(key, set())
                        if original in prior or (atomic and atomic in prior):
                            located = True
                    elif not located and replacement:
                        key = (claim["section_or_page_id"], claim["location_type"])
                        if "revision:" + replacement.strip() in resolved_page_claim_text.get(key, set()):
                            located = True
            if not located:
                originally_located = False
                if claim["location_type"] == "report_section":
                    # A prior overlapping claim may already have replaced this
                    # sentence in the working draft. Prove location against
                    # this claim's immutable P7 text before falling back to its
                    # atomic paraphrase, which may never have appeared verbatim.
                    for candidate_text in (claim_original_text, original, atomic):
                        if candidate_text:
                            _, originally_located = replace_once(original_markdown, candidate_text, "")
                            if originally_located:
                                break
                else:
                    original_page = original_pages.get(claim["section_or_page_id"], {})
                    if claim["location_type"] == "ppt_speaker_note":
                        original_text = str(original_page.get("speaker_notes", ""))
                    elif claim["location_type"] == "ppt_visual":
                        original_text = str(original_page.get("visual_suggestion", ""))
                    elif claim["location_type"] == "ppt_slide":
                        original_text = "\n".join([
                            str(original_page.get("title", "")), str(original_page.get("purpose", "")),
                            "\n".join(original_page.get("on_slide_text", [])),
                        ])
                    else:
                        original_text = "\n".join([
                            str(original_page.get("title", "")), str(original_page.get("purpose", "")),
                            "\n".join(original_page.get("on_slide_text", [])),
                            str(original_page.get("visual_suggestion", "")), str(original_page.get("speaker_notes", "")),
                        ])
                    _, originally_located = replace_once(original_text, original, "")
                    if not originally_located and action == "remove" and claim["location_type"] == "ppt_slide":
                        originally_located = unique_embedded_numeric_line(original_page, atomic or original) is not None
                if originally_located:
                    if action == "remove" or (action == "mark_unverified" and not replacement):
                        # An earlier duplicate/overlapping claim may already
                        # have removed this unsupported sentence from the
                        # working draft. Treat that action as idempotent only
                        # after proving the exact claim existed in the
                        # immutable original report/page. Its uncertainty is
                        # still retained in open_issues above.
                        located = True
                    if replacement and claim["location_type"] == "report_section":
                        markdown += "\n\n核验修订：%s" % replacement
                        located = True
                    elif replacement and page and claim["location_type"] == "ppt_speaker_note":
                        current_notes = str(page.get("speaker_notes", ""))
                        # A prior claim on the same page may already have
                        # applied this exact shared revision. Do not duplicate
                        # it merely because this claim's original wording is
                        # no longer present.
                        if replacement.strip() in current_notes:
                            located = True
                        else:
                            located = replace_note_verification(page, claim, replacement, result)
                    elif replacement and page and claim["location_type"] == "ppt_visual":
                        page["visual_suggestion"] = str(page.get("visual_suggestion", "")).replace(original, replacement, 1)
                        located = True
                    elif replacement and page and claim["location_type"] == "ppt_visual":
                        page["visual_suggestion"] = str(page.get("visual_suggestion", "")).replace(original, replacement, 1)
                        located = True
                    elif replacement and page:
                        candidate = replacement
                        if len(candidate) <= PPT_DENSITY_LIMITS["bullet_characters_max"] and sum(len(str(line)) for line in page.get("on_slide_text", [])) + len(candidate) <= PPT_DENSITY_LIMITS["page_characters_max"]:
                            page.setdefault("on_slide_text", []).append(candidate)
                        else:
                            if append_verification_note(page, claim["claim_id"], replacement):
                                page.setdefault("on_slide_text", []).append("该结论已按证据限定，完整修订见备注。")
                            else:
                                defer_page_revision(claim, replacement, result)
                        located = True
                if not located:
                    raise ValueError("无法在交付物中定位声明 %s，拒绝生成未落实核验结论的终稿" % claim["claim_id"])
            if located and claim["location_type"].startswith("ppt_"):
                key = (claim["section_or_page_id"], claim["location_type"])
                resolved_page_claim_text.setdefault(key, set()).update(item for item in (original, atomic) if item)
                if replacement:
                    resolved_page_claim_text[key].add("revision:" + replacement.strip())

        def clean_assembly_punctuation(value):
            text = str(value or "")
            # Verified removals can leave two consecutive connectors or stops.
            # This is punctuation-only repair; it must not reintroduce a claim.
            text = text.replace("此外，，因此", "因此")
            text = re.sub(r"，{2,}", "，", text)
            text = re.sub(r"。{2,}", "。", text)
            text = re.sub(r"；{2,}", "；", text)
            text = text.replace("。；", "。").replace("；。", "。").replace(".。", "。")
            text = text.replace("。，", "。").replace("，。", "。")
            # P8 may express an evidence boundary using an internal field name.
            # Translate only this exact audit phrase; retain its uncertainty.
            text = text.replace("但未提供对应 evidence_id 的独立证据条目", "但这一细节尚缺独立证据支持")
            return text.strip()

        markdown = clean_assembly_punctuation(markdown)
        final_pages = [{
            "page_id": page.get("page_id"), "navigation_title": page.get("navigation_title") or (page.get("title") if len(str(page.get("title") or "")) >= 2 else "研究主题"), "title": page.get("title"), "purpose": page.get("purpose", ""),
            "on_slide_text": [clean_assembly_punctuation(item) for item in page.get("on_slide_text", []) if clean_assembly_punctuation(item) and not (len(clean_assembly_punctuation(item)) < 20 and clean_assembly_punctuation(item).endswith(("：", ":")))], "visual_suggestion": page.get("visual_suggestion", "") if any(re.search(r"https://[^\s|;，,）)]+", str(ref.get("locator", ""))) for ref in page.get("figure_refs", [])) else "",
            "speaker_notes": clean_assembly_punctuation(page.get("speaker_notes", "")), "evidence_ids": page.get("evidence_ids", []),
            "figure_refs": [ref for ref in page.get("figure_refs", []) if re.search(r"https://[^\s|;，,）)]+", str(ref.get("locator", "")))], "source_citations": page.get("source_citations", []),
        } for page in pages]
        output = {
            "delivery_version": "P9-deterministic-1.0", "evidence_version": str(evidence_version),
            "final_report": {"title": report.get("report_title", "调研报告"), "markdown": markdown, "used_evidence_ids": list(report.get("used_evidence_ids", evidence_ids))},
            "final_ppt": {"deck_title": ppt.get("deck_title", "调研汇报"), "storyline": ppt.get("storyline", "证据驱动的研究综述"), "pages": final_pages},
            "verification_note": "已按独立核验结果确定性应用保留、降级、删除和未核实标记。",
            "open_issues": list(dict.fromkeys(item for item in open_issues if item)),
            "source_ids": list(source_ids), "evidence_ids": list(evidence_ids), "change_log": change_log,
        }
        output["final_ppt"]["pages"], page_repairs = repair_verified_pages(
            output["final_ppt"]["pages"], claims, verification, evidence_records
        )
        if page_repairs:
            output["verification_note"] += " 已使用P8核验句自动重建页面：" + ", ".join(item["page_id"] for item in page_repairs)
            repaired_claims = {claim_id for item in page_repairs for claim_id in item["claim_ids"]}
            for entry in output["change_log"]:
                if entry["claim_id"] in repaired_claims:
                    entry["reason"] += "；已同步用于整页要点和讲稿重建。"
        if reviewed_page_edits is not None:
            output = apply_reviewed_page_revisions(output, reviewed_page_edits, claims, verification)
        if overflow_revisions:
            evidence_source_by_id = {item.get("evidence_id"): item.get("source_id") for item in (evidence_records or [])}
            page_citations = {page.get("page_id"): page.get("source_citations", []) for page in pages}
            groups = {}
            for item in overflow_revisions:
                if item["text"]:
                    groups.setdefault(item["page_id"], []).append(item)
            next_page = max([int(match.group(1)) for page in output["final_ppt"]["pages"]
                             if (match := re.search(r"(\d+)$", str(page.get("page_id") or ""))) ] or [0]) + 1
            for source_page_id, items in groups.items():
                statements, used_ids, source_ids_for_page = [], [], set()
                for item in items:
                    if item["text"] not in statements:
                        statements.append(item["text"])
                    used_ids.extend(eid for eid in item["evidence_ids"] if eid in set(evidence_ids))
                    source_ids_for_page.update(evidence_source_by_id.get(eid) for eid in item["evidence_ids"] if evidence_source_by_id.get(eid))
                notes = "\n".join(statements)
                if len(notes) > PPT_DENSITY_LIMITS["speaker_notes_max"]:
                    raise ValueError("已核验的补充修订超出单页讲稿容量，不能截断科学限定：" + str(source_page_id))
                source_citations = [citation for citation in page_citations.get(source_page_id, [])
                                    if citation.get("source_id") in source_ids_for_page]
                output["final_ppt"]["pages"].append({
                    "page_id": "SL-%02d" % next_page, "navigation_title": "核验适用条件", "title": "研究结果的适用条件",
                    "purpose": "补充呈现经核验后必须保留的研究条件与范围",
                    "on_slide_text": ["关键结果需结合研究对象、队列构成与预设条件解读。"],
                    "visual_suggestion": "以简洁文字卡片呈现适用条件及对应来源。",
                    "speaker_notes": notes, "evidence_ids": list(dict.fromkeys(used_ids)),
                    "figure_refs": [], "source_citations": source_citations,
                })
                next_page += 1
            output["verification_note"] += " 已将无法安全放回原页的核验修订完整放入补充页。"
        validate_final(output, claim_ids, source_ids, evidence_ids, verification)
        if evidence_records is not None and source_records is not None:
            output["final_report"]["markdown"] = render_linked_report(markdown, evidence_records, source_records, report.get("figure_recommendations", []), figure_records or [])
            validate_final(output, claim_ids, source_ids, evidence_ids, verification)
        return output, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}

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
            allowed = set(evidence_ids)
            removed = []
            for claim in value.get("claims", []):
                cited = claim.get("cited_evidence_ids", [])
                if isinstance(cited, list):
                    invalid = [item for item in cited if item not in allowed]
                    if invalid:
                        removed.extend(invalid)
                        claim["cited_evidence_ids"] = [item for item in cited if item in allowed]
            if removed and isinstance(value.get("extraction_notes"), list):
                value["extraction_notes"].append(
                    "程序已移除模型生成但输入中不存在的 evidence_id：%s" % ", ".join(sorted(set(removed)))
                )
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

    def verify_claims(self, claims, evidence_records, source_records, tier, pro_claim_ids=None):
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
        groups = []

        def normalized_claim(item):
            text = re.sub(r"\[[^\]]+\]", "", str(item.get("atomic_claim", "")))
            return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff%]+", "", text).lower()

        def same_deterministic_claim(left, right):
            if left.get("claim_type") != right.get("claim_type") or left.get("risk_level") != right.get("risk_level"):
                return False
            if set(left.get("cited_evidence_ids", [])) != set(right.get("cited_evidence_ids", [])):
                return False
            left_text, right_text = normalized_claim(left), normalized_claim(right)
            if not left_text or not right_text:
                return False
            if left_text == right_text:
                return True
            shorter, longer = sorted((left_text, right_text), key=len)
            if len(shorter) / len(longer) < 0.82 or shorter not in longer:
                return False
            return re.findall(r"\d+(?:\.\d+)?%?", left_text) == re.findall(r"\d+(?:\.\d+)?%?", right_text)

        for claim in claim_items:
            matching = next((items for items in groups if same_deterministic_claim(items[0], claim)), None)
            if matching is None:
                groups.append([claim])
            else:
                matching.append(claim)
        representatives = [items[0] for items in groups]
        representative_to_group = {items[0]["claim_id"]: items for items in groups}
        representative_results = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}
        strong_types = {"causal", "efficacy", "safety", "approval"}
        eligible = [item for item in representatives if item.get("claim_type") in strong_types and item.get("risk_level") in ("medium", "high")]
        strong = [item for item in eligible if item.get("claim_id") in set(pro_claim_ids)] if pro_claim_ids is not None else eligible
        standard = [item for item in representatives if item not in strong]
        routes = []

        def normalize_verification(value, batch_items, batch_ids):
            claims_by_id = {item["claim_id"]: item for item in batch_items}
            allowed = set(evidence_ids)
            for result in value.get("results", []):
                result["valid_evidence_ids"] = [
                    item for item in result.get("valid_evidence_ids", []) if item in allowed
                ]
                status = result.get("support_status")
                if status == "supported":
                    result["action"] = "keep"
                    result["revised_claim"] = None
                elif status == "unsupported":
                    result["action"] = "remove"
                    result["revised_claim"] = None
                elif status == "cannot_determine":
                    result["action"] = "mark_unverified"
                    result["revised_claim"] = None
                elif status == "partially_supported":
                    original = claims_by_id.get(result.get("claim_id"), {}).get("atomic_claim", "").strip()
                    revised = str(result.get("revised_claim") or "").strip()
                    if result.get("action") != "revise" or not revised or revised == original:
                        result["support_status"] = "cannot_determine"
                        result["action"] = "mark_unverified"
                        result["revised_claim"] = None
                        explanation = str(result.get("explanation") or "").strip()
                        result["explanation"] = (explanation + " 程序未获得可用的降级表述，已保守标记为未核实。").strip()
            value["verification_version"] = str(value.get("verification_version") or "P8-normalized-1.0")
            value["summary"] = {
                status: sum(item.get("support_status") == status for item in value.get("results", []))
                for status in ("supported", "partially_supported", "unsupported", "cannot_determine")
            }
            value["summary"]["high_risk_remaining"] = 0
            return validate_verification(value, batch_ids, evidence_ids, batch_items)

        for batch_group, upgrade, label in ((standard, False, "standard"), (strong, True, "high_risk")):
            for batch_items in self._verification_batches(batch_group, evidence_by_id, upgrade):
                batch_ids = [item["claim_id"] for item in batch_items]
                cited_ids = {evidence_id for item in batch_items for evidence_id in item.get("cited_evidence_ids", [])}
                if upgrade:
                    cited_source_ids = {evidence_by_id[evidence_id].get("source_id") for evidence_id in cited_ids if evidence_id in evidence_by_id}
                    cited_ids.update(evidence_id for evidence_id, evidence in evidence_by_id.items() if evidence.get("source_id") in cited_source_ids)
                batch_evidence = [evidence_by_id[evidence_id] for evidence_id in cited_ids if evidence_id in evidence_by_id]
                source_ids = {item.get("source_id") for item in batch_evidence}
                batch_sources = [source_by_id[source_id] for source_id in source_ids if source_id in source_by_id]
                output_limit = self._verification_output_limit(batch_items, evidence_by_id, upgrade)
                partial, partial_usage, route = self.generate(
                    "P8", tier,
                    {"claims": {"claim_set_version": claims.get("claim_set_version", ""), "claims": batch_items, "extraction_notes": []}, "evidence_records": batch_evidence, "source_records": batch_sources, "output_contract": load_contract("P8")},
                    lambda value, ids=batch_ids, items=batch_items: normalize_verification(value, items, ids),
                    upgrade=upgrade, max_tokens=output_limit, max_attempts=3, request_timeout=90,
                )
                claims_by_id = {item["claim_id"]: item for item in batch_items}
                partial["results"] = [self.enforce_current_citation(result, claims_by_id[result["claim_id"]]) for result in partial["results"]]
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
