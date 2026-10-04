window.ROADMAP_DATA = {
  updatedAt: "2026-10-04",
  currentStage: "S1",
  stages: [
    {
      id: "S0", title: "校正文档与基线", status: "done",
      purpose: "让总规划、代码现状、价格表述和 GitHub 状态只保留一个事实版本。",
      output: "统一主规划、README、完成状态与测试基线。",
      decision: "无需产品决策，已直接执行。",
      paths: [
        { name: "零散修补", pros: "改动少", cons: "旧信息会继续冲突", verdict: "不采用" },
        { name: "单一事实源", pros: "状态统一、便于长期维护", cons: "首次整理稍慢", verdict: "已采用" }
      ],
      doneWhen: "文档与代码一致，测试通过。"
    },
    {
      id: "S1", title: "专用 Schema", status: "active",
      purpose: "把 P3—P9 输出从自由文本变成可校验、可重试、可导出的稳定结构。",
      output: "P3、P4、P5、P7、P8、P9 专用数据协议与契约测试。",
      decision: "无需业务决策，直接执行。",
      paths: [
        { name: "继续通用对象", pros: "开发快、限制少", cons: "字段漂移，核验和导出不稳定", verdict: "淘汰" },
        { name: "每阶段专用协议", pros: "可验证、可回归、可追溯", cons: "需要维护协议版本", verdict: "采用" }
      ],
      doneWhen: "错误字段会被拒绝，每阶段都有成功与失败样例。"
    },
    {
      id: "S2", title: "P3 筛选＋P4 证据底稿", status: "next",
      purpose: "把找到的论文变成有保留理由、证据边界和原文定位的可靠底稿。",
      output: "相关性、证据类型、保留理由、事实数字、条件、局限与定位。",
      decision: "默认使用经济模型初筛，高风险结论升级复核。",
      paths: [
        { name: "纯规则", pros: "便宜、稳定、容易解释", cons: "不理解复杂语义", verdict: "仅作兜底" },
        { name: "全部高推理模型", pros: "理解能力强", cons: "成本高、速度慢", verdict: "不采用" },
        { name: "经济模型＋风险升级", pros: "质量、速度和成本平衡", cons: "需要明确升级规则", verdict: "采用" }
      ],
      doneWhen: "每条资料都有筛选理由，每条证据都有来源、边界和定位。"
    },
    {
      id: "S3", title: "P5 报告＋P6 PPT 内容包", status: "planned",
      purpose: "形成学生可以直接使用的报告与逐页演示内容，而不是只给资料清单。",
      output: "报告、逐页标题与正文、演讲者注释、追问清单和来源映射。",
      decision: "暂不生成 PPTX，先验证内容价值。",
      paths: [
        { name: "直接生成 PPTX", pros: "交付感最强", cons: "模板、字体、版权、兼容和返工成本高", verdict: "后置" },
        { name: "结构化内容包", pros: "成本低、可复制、便于验证", cons: "仍需粘贴进学校模板", verdict: "采用" }
      ],
      doneWhen: "报告与 PPT 同源，注释不新增无来源事实，页数不为凑数扩张。"
    },
    {
      id: "S4", title: "P7—P9 核验闭环", status: "planned",
      purpose: "减少引用不支持结论、相关性冒充因果、动物实验外推临床等问题。",
      output: "原子声明、支持等级、问题代码、修订动作和最终装配。",
      decision: "证据不足时降级或删除，不允许模型自行补齐事实。",
      paths: [
        { name: "只检查终稿", pros: "流程短", cons: "难定位错误，报告与 PPT 易不同步", verdict: "不采用" },
        { name: "拆分→核验→装配", pros: "可解释、可修复、交付同步", cons: "增加结构转换和模型调用", verdict: "采用" }
      ],
      doneWhen: "每个外部事实可追溯，不支持和过度外推都有处理结果。"
    },
    {
      id: "S5", title: "端到端测试与工程底座", status: "planned",
      purpose: "让长任务可恢复、可取消、可观察，并证明多种主题都能稳定交付。",
      output: "五主题回归、SQLite、阶段事件、重试/取消/恢复和 Markdown 导出。",
      decision: "先 SQLite；出现多实例需求后再迁移 PostgreSQL。",
      paths: [
        { name: "立即 PostgreSQL＋队列", pros: "扩展性强", cons: "当前运维复杂度过高", verdict: "后置" },
        { name: "SQLite＋可迁移数据层", pros: "开发快、故障面小", cons: "不适合多实例高并发", verdict: "采用" }
      ],
      doneWhen: "五个主题重复跑通，中断可恢复，用户能看阶段并导出。"
    },
    {
      id: "S6", title: "商业规则、部署与验证", status: "decision",
      purpose: "在交付质量成立后，验证学生是否愿意付费、机构是否愿意分发。",
      output: "预览边界、价格、退款、保存周期、体验码、测试部署和反馈数据。",
      decision: "需要共同拍板；接入支付前必须冻结规则。",
      paths: [
        { name: "先支付再完善", pros: "更早测试收入", cons: "售后会掩盖产品价值问题", verdict: "不采用" },
        { name: "体验码内测→按次付费", pros: "先验证交付，再验证价格", cons: "收入验证稍晚", verdict: "采用" }
      ],
      doneWhen: "3 家小机构和学生完成真实任务，得到完成率、返工率和愿付价格。"
    }
  ]
};
