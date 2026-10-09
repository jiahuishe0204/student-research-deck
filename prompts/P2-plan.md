目标：把已确认意图转成可检索、可交付计划，不预写研究结论。输入 intent={{intent}}、tier={{tier}}、available_sources={{available_sources}}、runtime_config={{runtime_config}}。

先判断研究对象、用户要做的判断和最合适的学术展开方式，再生成结构。结构必须随主题变化，不能默认复用固定模板：疾病或病理现象通常从定义、临床意义、自然史/病理生理、研究模型与测量方法、干预策略、证据阶段和研究空白展开；药物或治疗主题关注作用机制、适应人群、疗效、安全性、比较基线、证据等级和监管状态；技术或方法主题关注原理、工作流、性能指标、基准、适用条件、局限和验证；机制主题关注观察、因果链、关键节点、模型证据、替代解释和可证伪问题；工程或平台主题关注需求、系统架构、关键瓶颈、策略、性能、稳定性、放大和转化。混合主题应组合必要模块，而不是把所有模块都堆上。

以“心脏瓣膜钙化”为例，合理的问题可能包括：钙化如何定义并与退行性改变区分；疾病负担与临床后果；细胞、分子和力学机制；体外、动物、影像或组织学方法如何研究；现有药物、器械或其他干预针对哪些环节；哪些方案只停留在前临床，哪些进入临床；关键争议和研究空白。示例只用于理解动态结构，不得机械复制到其他主题。

输出研究范围、排除项、3—6个不重复问题、证据需求、检索概念、来源计划、筛选与停止条件、报告结构、PPT叙事和风险。report_outline与ppt_story_arc必须来自本主题的核心问题和证据类型；每一部分说明它要回答什么，而不是只列通用章节名。快速版覆盖基础框架；深入版增加概念边界、方法学、比较、反证、冲突、适用条件和研究空白。

只输出一个 JSON 对象，且只能包含这 10 个键：`research_scope`、`exclusions`、`questions`、`search_concepts`、`source_plan`、`selection_criteria`、`stop_conditions`、`report_outline`、`ppt_story_arc`、`risks`。`exclusions`、`source_plan`、`selection_criteria`、`stop_conditions`、`report_outline`、`ppt_story_arc`、`risks` 必须是数组；`search_concepts` 必须是对象。`source_plan` 每项是一个来源方案，不得用包含“目标来源数”等键的对象代替数组。`questions` 必须有 3—6 项，每项只包含 `question_id`、`question`、`evidence_needs`，其中 `evidence_needs` 是字符串数组。输出必须符合 P2-plan.schema.json。
