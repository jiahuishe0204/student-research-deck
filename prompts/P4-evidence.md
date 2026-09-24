目标：从 source_text={{source_text}} 提取可定位证据。输入 source_record={{source_record}}、question_ids={{question_ids}}。每条证据保留source_id、fact、excerpt、locator、reading_scope、conditions、limitations。正文缺失时返回no_extractable_evidence。图片候选额外记录figure_id、caption、locator、supported_claims、reuse_status；版权或复用状态未知时不能标记为可直接嵌入。

