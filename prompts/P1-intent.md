目标：只理解主题，不检索、不写结论。输入 topic={{topic}}、tier={{tier}}、runtime_config={{runtime_config}}。规范主题并判断是否属于生命科学；能合理解释时直接输出确认文本，只有歧义实质改变范围、深度或交付结构时才返回一个澄清问题。不得因缺少场合、听众或时长而追问。

对只有一两个词的短主题，若它同时存在生命科学与非生命科学的常见含义（如“苹果”可指水果或科技公司），不得默认其中一种，必须澄清。

只输出一个 JSON 对象，且只能包含这 8 个键：`domain`、`normalized_topic`、`scope_hint`、`tier`、`assumptions`、`need_clarification`、`clarification_question`、`confirmation_text`。`need_clarification` 必须是布尔值；不需澄清时 `clarification_question` 必须为 null；需要澄清时只允许一个问题字符串，且 `confirmation_text` 必须为 null。输出必须符合 P1-intent.schema.json。
