目标：把 verified_report={{report}} 编排成学生可向老师、同学或上级汇报的 PPT 内容包，不生成 PPTX，不把报告机械切页。输入 intent={{intent}}、research_plan={{plan}}、evidence_records={{evidence_records}}、figure_records={{figure_records}}、source_records={{source_records}}、explicit_constraints={{constraints}}。

必须继承 research_plan 针对本主题生成的研究问题和叙事结构，不得重新套用通用模板。先建立符合该主题的学术故事线。每页只承担一个沟通任务，标题优先表达该页结论，听众只看标题和关键要点也能复述主线。案例页既要说明做了什么，也要回答它证明了什么、不能证明什么。页面保留关键数字、因果关系和可比较维度，完整条件、证据边界与讲解深度放在备注。

每页必须包含：标题、目的、上屏文字、视觉建议、简短讲稿、evidence_ids、figure_refs 和 source_citations。如有真实 figure_record，视觉建议必须说明用哪张图、它支持哪个结论、在原文哪里，并保留复用状态。如无可用原图，figure_refs 为空，视觉建议明确写“需补充图源”，不得虚构图号。

source_citations 只能引用 allowed_source_ids，根据 source_records 生成页下方可直接使用的 Vancouver 短引用，例如“Smith J, et al. J Am Coll Cardiol. 2024;83:123-135.”。来源元数据不完时不得猜测，用现有字段并在引用中标注“信息不完”。evidence_ids 只能从 allowed_evidence_ids 逐字选择，figure_id 只能从 allowed_figure_ids 逐字选择；不得改写、缩短或自行构造编号。

常规页面建议 3—5 个有层级的要点，数据页可按信息任务适度增加；只有出现接近正文段落的极端堆字时才视为结构失败。注释不得新增事实。输出必须严格符合 P6-ppt.schema.json。
