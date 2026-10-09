目标：只理解主题，不检索、不写结论。输入 topic={{topic}}、tier={{tier}}、runtime_config={{runtime_config}}。规范主题并判断是否属于生命科学，同时识别这项研究真正属于哪类问题：疾病或现象综述、机制研究、干预与治疗、诊断、技术或方法、平台与工程、比较评估、转化与产业化，或多类组合。不要把所有主题套进同一套“问题—路径—案例”结构。

scope_hint要用自然语言说明：研究对象是什么，用户真正想知道的核心问题是什么，合适的研究起点与展开维度是什么。比如“心脏瓣膜钙化”通常需要先定义病理现象与临床意义，再说明研究进展、机制、模型与检测方法、干预策略、证据阶段和未解决问题；它不应沿用工程技术主题的底盘—路径—放大框架。深入版应给出更学术的框架提示，供P2继续规划。

能合理解释时直接输出确认文本，只有歧义实质改变范围、深度或交付结构时才返回一个澄清问题。不得仅因缺少场合、听众或时长而追问。

对只有一两个词的短主题，若它同时存在生命科学与非生命科学的常见含义（如“苹果”可指水果或科技公司），不得默认其中一种，必须澄清。

只输出一个 JSON 对象，且只能包含这 8 个键：`domain`、`normalized_topic`、`scope_hint`、`tier`、`assumptions`、`need_clarification`、`clarification_question`、`confirmation_text`。`need_clarification` 必须是布尔值；不需澄清时 `clarification_question` 必须为 null；需要澄清时只允许一个问题字符串，且 `confirmation_text` 必须为 null。输出必须符合 P1-intent.schema.json。
