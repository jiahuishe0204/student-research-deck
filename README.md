# 调研交付台（student-research-deck）

面向中国高校本科生和研究生的按次调研交付产品规划。用户输入老师原话或研究主题，系统拟自动识别任务意图、规划调研路径、检索与核验资料，并输出可以直接用于汇报的调研报告与 PPT 逐页方案。

> 完整版规划已形成，正在分阶段实现证据链、交付生成与核验闭环。以 `调研交付台-PROMPT.md` 为主文档；商业规则未冻结前可以继续本地工程和内测准备，但不接真实支付、不公开投放。

## 产品承诺

- 不要求用户学习提示词。
- 普通课设：尽快得到结构清楚、来源可核对的交付底稿。
- 研究生初步调研：快速建立问题框架、技术路线与证据边界。
- 首版不直接生成 `.pptx`，先交付完整的 PPT 逐页内容和演讲者注释；后续再接入模板化幻灯片生成。
- 不提供论文代写、作业包过或虚构引用。

## 首版文件

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
- `model_usage.py`：逐次记录模型、阶段、成功/失败和 Tokens；可在下一次请求发出前按任务总 Tokens、Pro 调用次数或 Pro Tokens 上限停止。运行环境可配置 `MODEL_TASK_MAX_TOTAL_TOKENS`、`MODEL_PRO_MAX_CALLS`、`MODEL_PRO_MAX_OUTPUT_TOKENS`、`MODEL_PRO_MAX_TOTAL_TOKENS`，值为 `0` 表示暂不启用该项上限。
- `workflow_validation.py` 与 `contracts.py`：P1—P9 的跨阶段业务校验和 JSON 结构契约。
- `retrieval.py` 与 `epo_ops.py`：PubMed / Europe PMC / Crossref / EPO OPS 检索、去重及 EPO 周额度保护。
- `docs/公开数据源与边界.md`：数据源限速、版权、失败降级与上线边界。

## 本地预览

```bash
python3 server.py
```

确保上级目录 `.env` 中已设置 `DEEPSEEK_API_KEY`，然后打开 `http://127.0.0.1:4180`。密钥只在本地服务端读取，不会发送到浏览器。如果使用兼容网关，可在同一文件中设置 `DEEPSEEK_BASE_URL`。

执行版图可通过首页导航进入，也可以直接打开 `http://127.0.0.1:4180/roadmap.html`。它是静态网页，查看和筛选不会调用模型；阶段内容集中维护在 `web/roadmap-data.js`。

## 当前状态

这是从原“生命科学科研调研工作台”派生的商业化升级项目。已完成产品定义、P1—P9 工作流、任务持久化与归属令牌、公开论文数据源和 EPO OPS 本地接入、证据底稿、报告、PPT 内容包及独立引用核验的本地 MVP。EPO 采用 3 GB 创建者提醒、接近 4 GB 原子预留停止，并由 EPO 官方上限兜底。GitHub 私有远程仓库已经建立；剩余真实主题回归、线上 EPO 强一致计量写入、真实支付、PPTX、完整用户登录和公开部署尚未完成。
