目标：从 source_text={{source_text}} 提取可定位证据。输入 source_record={{source_record}}、figure_candidates={{figure_candidates}}、question_ids={{question_ids}}。每条证据保留 evidence_id、source_id、fact、excerpt、locator、evidence_type、conditions、limitations；reading_scope 必须反映实际读取的是摘要还是正文。正文缺失时将 extraction_status 设为 no_extractable_evidence 并说明原因。

只能从 figure_candidates 中选取与研究问题直接相关的原文图。figure_id 必须逐字复制候选编号，caption 保留原意，locator 同时保留 PMCID、图号和 article_figure_url，supported_claims 写明它能支持的结论。版权或复用状态未知时必须标记 unknown，不能标记为可直接嵌入。没有候选图时输出空数组，不得虚构。输出必须严格符合 P4-evidence.schema.json。
