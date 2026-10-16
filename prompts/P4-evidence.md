目标：从 source_text={{source_text}} 提取可定位证据。输入 source_record={{source_record}}、figure_candidates={{figure_candidates}}、question_ids={{question_ids}}、limits={{limits}}。每条证据保留 evidence_id、source_id、fact、excerpt、locator、evidence_type、conditions、limitations；reading_scope 必须反映实际读取的是摘要还是正文。只保留最能回答 question_ids 的证据，evidence_records 不得超过 limits.evidence_records_max，figure_records 不得超过 limits.figure_records_max。正文缺失时将 extraction_status 设为 no_extractable_evidence 并说明原因。

只能从 figure_candidates 中选取与研究问题直接相关的原文图。figure_id 必须逐字复制候选编号。caption 仅填候选图的简短图号标签（例如 Figure 1），不要抄写长图注：程序会按 figure_id 从候选记录原样恢复完整原文图注及分图含义。locator 同时保留 PMCID、明确的 Figure/Fig. 编号和 article_figure_url，supported_claims 写明它能支持的结论。若结论只由某个分图支持，supported_claims 必须明确写出对应分图，不能把整张多分图笼统描述成均支持该结论。无法确定具体图号或分图对应关系时不选择该图，禁止让下游用户自行猜图。版权或复用状态未知时必须标记 unknown，不能标记为可直接嵌入。没有候选图时输出空数组，不得虚构。输出必须严格符合 P4-evidence.schema.json。

证据条目以一个可核查结论为单位，不复制整段正文。fact 简明表达，excerpt 只引用直接支持该结论的原文句子；conditions 和 limitations 保留样本量、比较条件、剂量、时间及统计限制，避免在多个字段重复同一段原文。优先完整闭合 JSON，不增加契约之外的解释字段。

分图 a/b/c 的科学含义必须保留在原文图注中；supported_claims 的分图选择必须与其逐项相符。
