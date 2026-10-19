"""Opt-in narrative review gate: exact coverage, provenance and invalidation."""
import hashlib
import json
import copy
import re
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
            if isinstance(page,dict) and isinstance(page.get('segments'),list) and case.get('allowed_bridges'):
                compact=[]
                def approved(seg):
                    return isinstance(seg,dict) and set(seg)=={'kind','value'} and seg['kind']=='bridge' and seg['value'] in case['allowed_bridges']
                for seg in page['segments']:
                    if compact and approved(seg) and approved(compact[-1]):compact[-1]=seg
                    else:compact.append(seg)
                page['segments']=compact
    return result


def fingerprint(case, page, policy):
    return hashlib.sha256(json.dumps({'case':case,'page':page,'policy':policy},
                                    ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def render(case, page):
    result=validate_author({'pages':[page]},[case])[0]
    conflicts=uncertainty_conflicts(case,page)
    if conflicts:
        raise ValueError('未知被改写为确定否定：'+json.dumps(conflicts,ensure_ascii=False))
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

def uncertainty_conflicts(case,page):
    """Narrow deterministic guard; entities come from current claims, not a topic list."""
    uncertain=[]
    for cid,item in case['canonical'].items():
        for m in re.finditer(r'未证明由([^，。；（）]+?)(?:直接)?引起',item['text'] or ''):
            uncertain.append((cid,m.group(1)))
    errors=[]
    for i,segment in enumerate(page['segments']):
        if segment['kind']!='bridge':continue
        for cid,entity in uncertain:
            pattern=r'(?:而非|并非|不是)(?:由)?'+re.escape(entity)
            for m in re.finditer(pattern,segment['value']):
                prefix=segment['value'][max(0,m.start()-8):m.start()]
                if re.search(r'(?:不能|不应|不可)(?:据此)?(?:断言|宣称|说|认为)[“"\s]*$',prefix):continue
                errors.append({'location':f'segments/{i}','quote':m.group(),'claim_id':cid,
                               'repair':'保留未证明的限定，不将未知改成否定因果。'})
    return errors


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

def normalize_checks(value):
    value=copy.deepcopy(value)
    if isinstance(value,dict) and isinstance(value.get('checks'),list):
        for check in value['checks']:
            if isinstance(check,dict) and check.get('status')=='pass' and 'repair' not in check:
                check['repair']=''
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
