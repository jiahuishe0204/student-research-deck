目标：依据 verification_results={{verification_results}} 同步修订 draft_report={{draft_report}} 和 draft_ppt={{draft_ppt}}。supported保留；partially_supported降级；unsupported删除；cannot_determine删除或标未核实。修复语义断裂、悬空引用和空页，不引入新事实。PPT 交付物是内容包，不是 PPTX。修订每页时必须保留 navigation_title、purpose、visual_suggestion、figure_refs 和 source_citations；正文标题因核验而改变时，同步检查 navigation_title 是否仍准确，但不得把正文长标题直接复制成目录短标题。如删除某条结论，同步删除只支持该结论的图片与引用。输出最终报告、PPT内容包、核验说明、open_issues、来源与证据编号、版本和change_log，且必须严格符合 P9-final.schema.json。

标题同步契约：核验或改写页面后，重新检查 `navigation_title` 与 `title` 是否仍来自同一个页面沟通任务。`navigation_title` 保持“研究对象＋内容动作/分析维度”的短标题风格，`title` 在同一对象、同一证据边界内补足完整判断；不得因改动正文而留下过时、冲突或只剩泛词的短标题。

展示字段保留契约：最终每页必须原样保留非空 `navigation_title` 和 `title`。不得在确定性装配、修订或投影字段时删除 `navigation_title`；若改写 `title`，须同步复核短标题。目录使用 `navigation_title`，内容页同时显示它作为主标题、`title` 作为副标题。

客户可见层继承：终稿页面顶部只保留页码和标题，不得恢复 `EV::...`、内部来源 ID 或证据追踪串。`evidence_ids` 保留在最终数据和核验记录中，客户看到的来源统一使用作者、期刊、年份、DOI 和原文链接。

图源入口继承：终稿中的论文来源和原文图入口统一以 DOI 作为客户主链接；不得把 PubMed、Europe PMC 登录页、未经点击验证的深层图页或需要特定网络环境的 URL 作为主入口。图源链接只用于查看原文，不代表系统嵌入图片或取得复用许可。

客户交付风格继承：页下引用标题固定为“参考来源”，用作者缩写、期刊缩写、年份、卷期/页码和可点击 DOI 链接呈现；仅在确无 DOI 时使用已验证的论文原文链接。内部 evidence_ids 保留在终稿数据与审计链中，不得投影到客户页面。

配图显示门槛：若页面没有带可点击、可核验 https 链接的 figure_refs，终稿中必须将 visual_suggestion 置空且 figure_refs 置空，客户交付完全省略配图建议与图源区块；禁止用自行绘图建议、缺图说明或占位内容代替。只有图源链接真实存在且对应建议中的具体原文图时才显示该区块。
