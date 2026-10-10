目标：在用户已确认题目的前提下，先设计整篇报告的大故事，再展开各部分的小故事和证据计划；不预写研究结论。输入 intent={{intent}}、tier={{tier}}、available_sources={{available_sources}}、runtime_config={{runtime_config}}。

第一步设计“大故事”：忠实继承intent.normalized_topic，不擅自换题。说明报告最终需要让读者理解什么、从哪里讲起、3—6个主要内容模块如何逐层展开，以及上一部分为什么自然引出下一部分。模块可以承担概念与背景、现象描述、机制说明、技术路线、研究进展、疗效与安全、患者选择、转化障碍或其他本主题真正需要的功能。关系由内容决定，不强制套用“前提—验证—转化—比较—反证”，也不要求所有主题都被压缩成一句中心假设。

第二步设计“小故事”：把每个主要模块拆成具体内容节点，说明这一部分要讲清什么、需要什么资料、如何衔接下一部分。内容节点可以是概念、现象、机制、实验发现、临床观察、技术路线或应用，不强制写成问句。为了兼容现有结构，questions字段仍保存3—6个内部检索任务，但这些任务只用于证据获取，不能反过来支配客户正文结构；question写成需要查明的具体事项，evidence_needs写明研究设计、对象、测量、比较或官方资料需求。

research_scope必须包含：用户确认的题目、整篇要讲明的内容、大故事摘要、范围边界和选择当前顺序的理由。report_outline写大故事及小故事的可执行章节蓝图，每项应包含该部分的内容目的、主要内容和与下一部分的衔接，不得只列“背景、现状、挑战、展望”等空标题。ppt_story_arc仅作为下游兼容字段，概括可用于口头汇报的叙事顺序；本次调研报告不进行PPT装配。

随后生成证据需求、检索概念、来源计划、纳排标准和停止条件。search_concepts应支持多组针对性检索，不得只给一个过宽的OR查询。来源组合优先权威综述用于建立全貌、原始研究用于支撑关键发现、临床注册或监管记录用于状态判断；检索计划必须能区分全文、摘要和元数据阅读层级。

成本与结构要求：本阶段是设计蓝图，不是撰写正文。整个JSON以3000个中文字以内为目标；report_outline和ppt_story_arc各3—6项，每项用1—3句说清内容和衔接；其他数组只保留会改变执行的条目。不重复同一说明，不在多个字段重写相同背景。

能力边界与选择规则：本阶段只设计内容路线和证据计划，不得虚构答案、数值、论文、药物或监管结论。题目若仍未由用户确认，应停止并要求确认，不替客户选方向。exclusions只保留会使当前故事明显发散的相邻内容，不为凑数设置硬下限。内部检索任务应共同覆盖内容蓝图，避免重复；没有证据时规划如何确认未知，不把计划语言写成事实。

只输出一个 JSON 对象，且只能包含这 10 个键：`research_scope`、`exclusions`、`questions`、`search_concepts`、`source_plan`、`selection_criteria`、`stop_conditions`、`report_outline`、`ppt_story_arc`、`risks`。`exclusions`、`source_plan`、`selection_criteria`、`stop_conditions`、`report_outline`、`ppt_story_arc`、`risks` 必须是数组；`search_concepts` 必须是对象。`questions` 必须有 3—6 项，每项只能包含 `question_id`、`question`、`evidence_needs`，不得添加title、purpose、rationale、transition或其他键。输出必须符合 P2-plan.schema.json。
