"""Nonfactual transitions: new scientific explanations must become verified claims."""
LINKS=(
    '围绕本页问题，先看现有证据能回答什么。',
    '理解这项观察，还需要考虑下面的限定。',
    '接下来考察另一项证据，区分它回答的问题。',
    '这些内容之间能建立怎样的联系？还需要哪些证据？',
    '下面回到结论的适用范围与尚未确定的问题。',
    '接下来沿研究框架，继续讨论尚未回答的问题。',
)

def bind_links(case):
    return dict(case,allowed_bridges=list(LINKS))
