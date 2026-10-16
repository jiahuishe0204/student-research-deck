"""Opt-in narrative review gate: exact coverage, provenance and invalidation."""
import hashlib
import json
import copy
from narrative_contract import validate_author


def normalize_envelope(value, cases):
    """Only strip an exact transport label; no scientific text is rewritten."""
    result=copy.deepcopy(value)
    if isinstance(result,dict) and result.get('type')=='json_object':
        result.pop('type')
    if isinstance(result,dict) and isinstance(result.get('pages'),list) and len(result['pages'])==len(cases):
        for page,case in zip(result['pages'],cases):
            if isinstance(page,dict) and 'figure_choices' not in page and not case['source_figures']:
                page['figure_choices']=[]
    return result


def fingerprint(case, page, policy):
    return hashlib.sha256(json.dumps({'case':case,'page':page,'policy':policy},
                                    ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def render(case, page):
    result=validate_author({'pages':[page]},[case])[0]
    if not any(s['kind']=='bridge' and s['value'].strip() for s in page['segments']):
        raise ValueError('讲稿没有问题组织或解释片段')
    figures={f['figure_id']:f for f in case['source_figures']}
    evidence_sources=case.get('evidence_sources',{})
    for selected in page['figure_choices']:
        figure=figures[selected['figure_id']]
        for cid in selected['claim_ids']:
            sources={evidence_sources.get(e) for e in case['canonical'][cid]['evidence_ids']}
            if not figure.get('source_id') or figure['source_id'] not in sources:
                raise ValueError('图源与主张来源不匹配')
    return result


def units(case, page):
    output=[]
    for i,s in enumerate(page['segments']):
        text=case['canonical'].get(s['value'],{}).get('text') if s['kind']=='claim' else s['value']
        output.append({'location':f'segments/{i}','text':text or '', 'kind':s['kind']})
    for i,f in enumerate(page['figure_choices']):
        output.append({'location':f'figure_choices/{i}','text':json.dumps(f,ensure_ascii=False),'kind':'figure'})
    output.append({'location':'overview','text':'\n'.join(u['text'] for u in output),'kind':'overview'})
    return output


def validate_checks(value, expected):
    if not isinstance(value,dict) or set(value)!={'checks'} or not isinstance(value['checks'],list):
        raise ValueError('审查结构错误')
    if [x.get('location') for x in value['checks']] != [u['location'] for u in expected]:
        raise ValueError('审查遗漏、重复或错位')
    for check,unit in zip(value['checks'],expected):
        if set(check)!={'location','status','quote','reason','evidence','repair'} or check['status'] not in ('pass','fail'):
            raise ValueError('审查字段错误')
        if any(not isinstance(v,str) for v in check.values()) or not check['reason'] or not check['evidence']:
            raise ValueError('审查缺少依据')
        if check['status']=='fail':
            if not check['quote'] or check['quote'] not in unit['text'] or not check['repair']:
                raise ValueError('审查没有引用该位置的真实文字或修正办法')
        elif check['quote'] or check['repair']:
            raise ValueError('通过项仍带修正，结论不一致')
    return value


def seal(case,page,review,policy):
    render(case,page)
    validate_checks(review,units(case,page))
    if any(c['status']!='pass' for c in review['checks']):
        raise ValueError('语义审查未通过')
    return {'fingerprint':fingerprint(case,page,policy),'review':review}


def validate_seal(case,page,approval,policy):
    if approval.get('fingerprint')!=fingerprint(case,page,policy):
        raise ValueError('主张、图源、框架、文本或规则变化，旧审查已失效')
    seal(case,page,approval['review'],policy)
    return True
