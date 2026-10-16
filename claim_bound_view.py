"""Experimental claim-bound view. Not yet wired into the public P6/P9 path."""
import copy
from workflow_validation import validate_ppt_density


def canonical_claims(claims, verification, evidence_registry=None):
    verdicts = {v['claim_id']: v for v in verification['results']}
    if len(verdicts) != len(verification['results']):
        raise ValueError('重复核验编号')
    result = {}
    for claim in claims:
        cid = claim['claim_id']
        if cid in result or cid not in verdicts:
            raise ValueError('重复或缺少主张核验')
        verdict = verdicts[cid]
        pair = verdict['support_status'], verdict['action']
        if pair == ('supported', 'keep'):
            text = claim['original_text']
        elif pair == ('partially_supported', 'revise'):
            text = verdict.get('revised_claim') or ''
        elif pair in (('unsupported', 'remove'), ('cannot_determine', 'mark_unverified')):
            text = None
        else:
            raise ValueError('不一致的核验状态')
        valid = sorted(set(claim.get('cited_evidence_ids', [])) & set(verdict.get('valid_evidence_ids', [])))
        migration = []
        if pair == ('partially_supported', 'revise') and evidence_registry is not None:
            # A revision may repair a citation, but only an explicitly verified,
            # existing record from a verified source can enter the registry.
            for eid in sorted(set(verdict.get('valid_evidence_ids', [])) - set(valid)):
                record = evidence_registry.get(eid)
                if not record or record.get('source_id') not in verdict.get('source_identity', {}).get('source_ids', []):
                    raise ValueError('修订引用缺少原始证据或来源核验')
                migration.append(eid)
            valid = sorted(set(valid) | set(migration))
        if text is not None:
            text = text.strip()
            if not text or text.endswith(('，', '、', ':', '：')) or not valid:
                raise ValueError('主张不完整或缺少有效原引用')
        result[cid] = {'text': text, 'evidence_ids': valid}
        if migration:
            result[cid]['citation_migration'] = {'original_ids': claim.get('cited_evidence_ids', []), 'added_verified_ids': migration}
    return result


def render_bound_page(layout, canonical, topic_titles, source_figures=()):
    """All factual strings come from one canonical registry, never layout text.

    Topic titles and original figure metadata are trusted inputs, not generated
    factual assertions. Fail on missing coverage rather than silently dropping it.
    """
    expected = {'page_id', 'topic_key', 'title_claim_ids', 'bullet_claim_ids',
                'note_claim_ids', 'visual_claim_ids', 'figure_ids'}
    if not isinstance(layout, dict) or set(layout) != expected:
        raise ValueError('布局包含无编号自由文本或缺少字段')
    if layout['topic_key'] not in topic_titles:
        raise ValueError('未知中性主题标题')
    field_names = ['title_claim_ids', 'bullet_claim_ids', 'note_claim_ids', 'visual_claim_ids']
    for field in field_names:
        ids = layout[field]
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('编号列表无效或重复')
        if not set(ids) <= set(canonical):
            raise ValueError('未知主张编号')
    active = {cid for cid, value in canonical.items() if value['text'] is not None}
    if not active or not active <= set(layout['note_claim_ids']):
        raise ValueError('空页或讲稿遗漏有效主张')
    def texts(field):
        return [canonical[cid]['text'] for cid in layout[field] if canonical[cid]['text'] is not None]
    bullets = texts('bullet_claim_ids')
    if not bullets:
        raise ValueError('没有完整上屏要点')
    figures = {f['figure_id']: f for f in source_figures}
    if len(figures) != len(source_figures) or len(set(layout['figure_ids'])) != len(layout['figure_ids']):
        raise ValueError('重复图源编号')
    if set(layout['figure_ids']) != set(figures):
        raise ValueError('图源遗漏或新增')
    page = {'page_id': layout['page_id'],
            'title': '。'.join(texts('title_claim_ids')) or topic_titles[layout['topic_key']],
            'on_slide_text': bullets,
            'speaker_notes': '\n'.join(t.rstrip('。') + '。' for t in texts('note_claim_ids')),
            'visual_suggestion': '\n'.join(texts('visual_claim_ids')),
            'evidence_ids': sorted({eid for cid in active for eid in canonical[cid]['evidence_ids']}),
            # Preserve original captions/provenance, not the old interpretation.
            'source_figures': [copy.deepcopy(figures[fid]) for fid in layout['figure_ids']]}
    validate_ppt_density([page])
    return page
