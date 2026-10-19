"""Shared structure/coverage contract for claim-bound narrative pages."""


def validate_author(value, inputs):
    if not isinstance(value, dict) or set(value) != {'pages'} or not isinstance(value['pages'], list) or len(value['pages']) != len(inputs):
        raise ValueError('页面数量或字段错误')
    rendered = []
    for page, case in zip(value['pages'], inputs):
        if not isinstance(page, dict) or set(page) != {'page_id', 'topic_key', 'segments', 'figure_choices'} or page['page_id'] != case['page_id'] or page['topic_key'] != case['topic_key']:
            raise ValueError('页面身份或字段错误')
        if not isinstance(page['segments'], list) or not isinstance(page['figure_choices'], list):
            raise ValueError('片段或图片列表错误')
        seen, text = [], []
        for segment in page['segments']:
            if not isinstance(segment, dict) or set(segment) != {'kind', 'value'} or not isinstance(segment['value'], str):
                raise ValueError('片段错误')
            if segment['kind'] == 'claim':
                cid = segment['value']
                fact = case['canonical'].get(cid, {}).get('text')
                if not fact:
                    raise ValueError('未知或撤下的主张')
                seen.append(cid)
                text.append(fact)
            elif segment['kind'] == 'bridge':
                if 'allowed_bridges' in case and segment['value'] not in case['allowed_bridges']:
                    raise ValueError('转场必须逐字选自allowed_bridges；科学解释须先进入主张核验，不能在转场新增')
                text.append(segment['value'])
            else:
                raise ValueError('未知片段类型')
        active = {cid for cid, item in case['canonical'].items() if item['text']}
        if not active or set(seen) != active or len(seen) != len(set(seen)):
            raise ValueError('有效主张遗漏、重复或空页')
        if len('\n'.join(text)) > 800:
            raise ValueError('讲稿过长，不得截断')
        selected_ids = []
        for figure in page['figure_choices']:
            if not isinstance(figure, dict) or set(figure) != {'figure_id', 'claim_ids', 'panel', 'reason'}:
                raise ValueError('配图结构错误')
            if not isinstance(figure['claim_ids'], list) or not all(isinstance(cid, str) for cid in figure['claim_ids']):
                raise ValueError('配图主张编号错误')
            if figure['figure_id'] not in {f['figure_id'] for f in case['source_figures']} or not figure['claim_ids'] or not set(figure['claim_ids']) <= active:
                raise ValueError('配图结构错误')
            if any(not isinstance(figure[key], str) or not figure[key].strip() for key in ('figure_id', 'panel', 'reason')):
                raise ValueError('配图缺少定位或说明')
            if len(set(figure['claim_ids'])) != len(figure['claim_ids']):
                raise ValueError('配图主张重复')
            selected_ids.append(figure['figure_id'])
        if len(set(selected_ids)) != len(selected_ids):
            raise ValueError('配图重复')
        rendered.append(dict(page, speaker_notes='\n'.join(text)))
    return rendered
