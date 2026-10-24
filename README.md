# 调研交付台（student-research-deck）

[![产品演示](https://img.shields.io/badge/在线演示-GitHub%20Pages-0969da?logo=github)](https://jiahuishe0204.github.io/student-research-deck/)
[![CI](https://github.com/jiahuishe0204/student-research-deck/actions/workflows/ci.yml/badge.svg)](https://github.com/jiahuishe0204/student-research-deck/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**在线演示：** https://jiahuishe0204.github.io/student-research-deck/

> 演示站用于展示产品界面与交互流程。完整的检索、模型生成和任务持久化能力需要在本地配置服务端与 API 密钥后运行。

面向中国高校生命科学相关专业本科生和研究生的按次科研调研交付产品。它主要服务不准备长期走科研道路、但仍需完成专业课或组会调研汇报的学生，帮助他们节省检索、整理和制作精力，同时得到体面、专业、有来源的调研报告与PPT逐页内容包。用户输入一个主题；主题较宽时先选择研究焦点，随后由系统完成资料检索、证据核验、报告写作和汇报内容组织。

> 完整版规划已形成，正在分阶段实现证据链、交付生成与核验闭环。以 `调研交付台-PROMPT.md` 为主文档；商业规则未冻结前可以继续本地工程和内测准备，但不接真实支付、不公开投放。

## 产品承诺

- 不要求用户学习提示词。
- 不要求用户一开始就知道宽泛主题应该从哪个方向展开；系统提供方向选项，最终焦点由用户确认。
- 普通课设与课程汇报：尽快得到结构清楚、来源可核对的报告和PPT内容。
- 研究生初步调研：建立主题特异的研究框架、技术路线、关键证据与研究边界。
- 首版不直接生成 `.pptx`，先交付完整的 PPT 逐页内容和演讲者注释；后续再接入模板化幻灯片生成。
- 公开上线时采用邮箱验证码登录；成果生成后邮件通知用户，并通过登录后可访问的安全链接交付，不默认发送大附件。
- 不提供论文代写、作业包过或虚构引用。

## 首版文件

- `docs/项目总内容包.md`：项目总入口与长期记忆；汇总已确认的产品、工程、提示词、界面、验收和同步规则。
- `docs/产品剩余任务清单-2026-10-11.md`：合并当前项目和相关任务后的已完成范围、剩余任务、验收标准与固定执行顺序。
- `docs/阶段总结-PPT内容升级与降本增效.md`：近期PPT内容质量、模型分层、成本保护和跨主题验证工作的可读总结。
- `调研交付台-PROMPT.md`：第一份总规划性质主文档，统一需求、流程、提示词、商业化和验收。
- `docs/产品与使用场景.md`：用户动机、场景、版本和交付形态。
- `docs/智能工作流与模型路由.md`：意图识别、规划、执行、核验的模型分层。
- `docs/流量投放与运营.md`：渠道、合作方式、实验和指标。
- `config/model-routing.json`：模型路由的机器可读初稿。
- `contracts.py` 与 `schemas/`：P1—P9 的结构协议；P3—P9 已全部使用专用协议并具备契约测试。
- `web/`：可交互首页原型，覆盖主题输入、版本选择、单问题澄清和交付预览；`roadmap.html` 是可长期复用的执行与决策版图。
- `tests/validate_project.py`：结构与关键承诺校验。
- `tests/run_prompt_smoke.py`：P1/P2 真实 DeepSeek 重复测试。
- `tests/fixtures/regression-topics.json`：五个代表主题的固定回归矩阵；日常执行免费离线契约测试，正式内测前执行真实模型回归。
- `server.py`：本地 HTTP API 与 P1—P9 流程编排。
- `model_client.py` 与 `model_routing.py`：可校验重试的 DeepSeek 调用以及配置驱动的模型选择。
- `model_usage.py`：逐次记录模型、阶段、成功/失败和 Tokens；可在下一次请求发出前按人民币费用、任务总 Tokens、Pro 调用次数或 Pro Tokens 上限停止。费用停止器按官方高峰价并假设输入全部缓存未命中进行保守预留。运行环境可配置 `MODEL_TASK_MAX_COST_CNY`、`MODEL_TASK_MAX_TOTAL_TOKENS`、`MODEL_PRO_MAX_CALLS`、`MODEL_PRO_MAX_OUTPUT_TOKENS`、`MODEL_PRO_MAX_TOTAL_TOKENS`，值为 `0` 表示暂不启用该项上限。
- `workflow_validation.py` 与 `contracts.py`：P1—P9 的跨阶段业务校验和 JSON 结构契约。
- `retrieval.py`、`patsnap_mcp.py` 与 `epo_ops.py`：PubMed / Europe PMC / Crossref / 专利检索和去重。比赛版通过中国区智慧芽 MCP 获取最多 3 条专利书目；EPO 仅保留为可回退提供方。配置 `PATSNAP_API_KEY` 后仍可额外调用另一账户的智慧芽医学文献 REST API。
- `docs/公开数据源与边界.md`：数据源限速、版权、失败降级与上线边界。

## 本地预览

```bash
python3 server.py
```

确保上级目录 `.env` 中已设置 `DEEPSEEK_API_KEY`，然后打开 `http://127.0.0.1:4180`。密钥只在本地服务端读取，不会发送到浏览器。如果使用兼容网关，可在同一文件中设置 `DEEPSEEK_BASE_URL`。

智慧芽为可选数据源：在同一 `.env` 中设置 `PATSNAP_API_KEY` 后启用。当前接入 B011 医学文献检索与 B030 文献详情；未设置时保持原有公共数据源流程。密钥仅用于服务端 `Authorization: Bearer` 请求，不写入任务产物或前端。

比赛版专利检索使用独立中国区 MCP 账户：设置 `PATENT_PROVIDER=patsnap_mcp_cn`、`PATSNAP_MCP_URL=https://connect.zhihuiya.com/1458a4/mcp` 和 `PATSNAP_MCP_API_KEY`。该密钥与医学文献 REST API 的 `PATSNAP_API_KEY` 分开；每个检索任务只在首条查询调用一次 `search_patents`，最多返回 3 条。

执行版图可通过首页导航进入，也可以直接打开 `http://127.0.0.1:4180/roadmap.html`。它是静态网页，查看和筛选不会调用模型；阶段内容集中维护在 `web/roadmap-data.js`。

## 当前状态

这是从原“生命科学科研调研工作台”派生的商业化升级项目。已完成产品定义、P1—P9 工作流、任务持久化与归属令牌、公开论文数据源和 EPO OPS 本地接入、证据底稿、报告、PPT 内容包及独立引用核验的本地 MVP。EPO 采用 3 GB 创建者提醒、接近 4 GB 原子预留停止，并由 EPO 官方上限兜底。公开仓库与静态产品演示已经建立；剩余真实主题回归、线上 EPO 强一致计量写入、真实支付、PPTX、完整用户登录和生产环境部署尚未完成。

生产版本只保留本仓库的 P1—P9 业务流程。旧原型中已验证的 EdgeOne 同域入口、安全响应头、健康探针、审计与备份要求正在迁入本仓库；旧四步生成、Blob 任务结构和旧客户界面不再继承。融合边界、部署位置和完成判定见 `docs/生产底座融合实施与验收-2026-10-19.md`。
