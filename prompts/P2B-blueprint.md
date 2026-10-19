目标：将已确认的大故事展开为小故事、内部检索任务和证据计划。输入 intent={{intent}}、research_architecture={{research_architecture}}、available_sources={{available_sources}}、runtime_config={{runtime_config}}。

必须继承research_architecture已确定的题目、模块和顺序，不重新搭建另一个大框架。把每个模块展开为具体内容节点，说清该部分要讲什么、需要哪类证据、如何过渡到下一部分。内容节点不强制写成问句。

questions只是下游检索使用的3—6个内部任务，不能支配客户正文的标题。每个任务只能包含question_id、question和evidence_needs。search_concepts按内容节点分组，使用适合PubMed/Europe PMC的英文词组；不只返回一个过宽查询。若available_sources含Patsnap，额外提供patsnap_terms数组（最多3个简短英文自然语言主题词组，不写AND/OR、字段标签或长布尔式），用于药物、靶点、疾病及适应症相关论文发现；不要把Patsnap聚合记录当作独立于其底层论文的证据。

report_outline必须与大故事模块一一对应，每项用1—3句说明小故事与衔接。source_plan、selection_criteria、stop_conditions和risks只保留会改变执行的条目。不写最终结论，不虚构文献、数据或监管状态。

只输出符合P2B-blueprint.schema.json的JSON对象。
