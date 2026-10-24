# 腾讯云交付服务部署清单

本目录只保存无密钥模板。真实账号标识、存储桶、域名和密钥不得提交仓库。

`functions.template.json` 固化四类函数的入口、定时器、超时、并发和环境变量边界。它是部署输入模板，不包含真实资源标识；部署前将其中角色名称映射到用户账号内的CAM角色。

## 函数与触发器

- API 函数：签发/验证验证码、会话鉴权、下载地址申请。
- 任务 API：由已验证会话创建任务、原子占用体验额度并查询任务进度。
- 任务 Worker：每分钟从 PostgreSQL 队列原子领取一个阶段作业；租约 fencing 防止旧实例覆盖新结果。P9 使用带 COS 权限的独立角色发布三类私有交付物。
- Outbox 定时函数：每分钟执行 `delivery_scf_entrypoint.main_handler`，事件为 `{"action":"outbox"}`。
- 保留期定时函数：每五分钟执行同一入口，事件为 `{"action":"retention"}`。
- 对账定时函数：每小时执行同一入口，事件为 `{"action":"reconcile"}`。
- 告警定时函数：每五分钟执行同一入口，事件为 `{"action":"monitor"}`；非零积压会令函数失败并触发云监控。

部署包安装 `requirements-scf.txt`。Outbox 与 COS 使用两个不同的 SCF 函数角色：SES 角色只能发送邮件；COS 角色只能访问指定桶的 `deliveries/` 前缀。若平台只能使用静态凭据，也必须使用两个独立 CAM 子账号并由密钥管理服务注入，不能写入代码或日志。

## COS 强制项

- 私有读写，禁止公共 ACL，禁止把 `deliveries/` 配为 CDN 公共回源。
- 服务端加密 AES256；应用删除为主，存储桶生命周期规则以七天为兜底。
- 跨用户、过期、已删除三类下载反例均应返回相同拒绝结果。

## SES 强制项

- 发信域名通过 DNS 验证，启用 SPF、DKIM，建议设置 DMARC。
- 三个模板分别用于验证码、完成通知、到期提醒；模板变量必须与代码白名单一致。
- 退信/投诉、永久失败、`unknown` 事件和发送费用达到阈值时告警。

## 尚需真实云端完成

1. 按顺序在 PostgreSQL 执行 `migrations/006_research_task_queue.sql` 和 `migrations/007_workflow_transitions.sql`，并保存迁移证据。
2. 确认 SCF/COS 地域和已备案或可验证的发信域名。
3. 创建私有桶、生命周期规则、最小权限角色和三个 SES 模板。
4. 通过服务端环境注入配置，执行快速版、深入版各一次端到端冒烟。
5. 保存不含邮箱、验证码、密钥和签名链接的请求编号、对象哈希与删除证据。

任务 Worker 将模型执行和阶段推进拆成两个持久步骤。模型结果成功落库后，推进失败只重试编排，不重复调用已经成功的模型或专利检索。P1 完成后等待用户确认方向；调用 `POST /tasks/{task_id}/continue` 后，服务端依次编排 P2—P9，其中 P4 按保留来源扇出并在全部成功后汇总。

P9 不直接把任务标记为完成。Worker 先以确定性对象键上传 `report`、`ppt_content`、`references` 三类文件，逐个核验 SHA-256、大小和 AES256 服务端加密；第三类文件也成功后，数据库才原子发布下载权限、完成任务并写入邮件 Outbox。重复执行会复用相同对象与产物标识。

交付阅读页支持 `delivery.html?task=TASK-...`。该模式只调用同源 `/tasks/{task_id}/delivery` 和 `/delivery/download`，携带 HttpOnly 会话 Cookie；下载请求还必须携带邮箱验证时返回、仅保存在当前标签页的 CSRF Token。无 `task` 参数时仍显示仓库内的验收样本。部署时必须由 EdgeOne 将这两个同源路径转发到独立 SCF 函数 URL，不能把上游地址或网关密钥注入浏览器脚本。

首页通过同源 `/api/health` 自动探测生产网关。只有网关明确返回 `runtime=edgeone-gateway` 且健康时，页面才显示邮箱验证码登录并改用 `/tasks`、`/tasks/{task_id}/progress` 和 `/tasks/{task_id}/continue`；未配置、不可达或本地开发时继续使用原有演示流程。生产部署必须通过 EdgeOne Cloud Functions 将 `/auth/*`、`/tasks*` 与 `/delivery/download` 分别转发到独立 SCF 函数 URL，并保留 Cookie 和 `X-CSRF-Token` 请求头。旧 API 网关触发器已经退出服务，不作为新部署方案。

## 告警、恢复与回滚

- 云监控对函数错误、邮件 `unknown/permanent_failed`、删除八次失败、孤儿对象、OTP请求量突增和当月费用设置告警。金额阈值由用户批准后填写，不能由程序擅自承诺费用。
- 数据库恢复目标：正式上线前由实际 PostgreSQL 供应商备份能力确定 RPO/RTO，并完成一次隔离恢复；恢复库不得重新发送历史 Outbox 邮件。
- COS 删除恢复：下载权限先关闭，再重试删除；`404/NoSuchKey` 视为已完成。八次失败进入人工处置，不能重新开放下载。
- 应用回滚：回退 SCF 代码版本但不反向删除数据库列；数据库使用前向修复迁移。若新版本异常，先关闭HTTP入口与定时触发器，再回退函数版本。
- 身份密钥或云凭据疑似泄露时，立即停用入口、轮换对应独立凭据并审计日志；不得把密钥值写入事故记录。

逐项证据记录使用 `acceptance-evidence-template.md`，没有真实证据的条目保持“未通过”。
