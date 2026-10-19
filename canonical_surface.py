"""Preserve provenance while preventing arithmetic conflicts from becoming facts."""
import copy
import re
from decimal import Decimal

EVIDENCE_ID=re.compile(r'EV::[A-Za-z0-9:._/-]+::\d{3}')
PROPORTION=re.compile(r'(?<![\d.≥≤<>])(?P<p>\d+(?:\.\d+)?)\s*%\s*[（(]\s*(?P<n>\d+)\s*/\s*(?P<d>\d+)\s*[)）]')

def ratio_conflicts(text):
    conflicts=[]
    for match in PROPORTION.finditer(text):
        p,n,d=match.group('p','n','d')
        decimals=len(p.split('.')[1]) if '.' in p else 0
        tolerance=Decimal(5)*(Decimal(10)**(-decimals-1))
        implied=None if int(d)==0 else Decimal(n)*100/Decimal(d)
        if implied is None or abs(Decimal(p)-implied)>tolerance:
            conflicts.append({'reported':match.group(0),'percentage':p,'numerator':n,'denominator':d,
                              'computed_percentage':None if implied is None else str(implied)})
    return conflicts

def spoken_text(text, allowed_ids):
    found=set(EVIDENCE_ID.findall(text))
    if not found<=set(allowed_ids):
        raise ValueError('正文引用未核验的证据编号，不能静默清除')
    for evidence_id in sorted(found,key=len,reverse=True):
        text=text.replace('['+evidence_id+']','').replace(evidence_id,'')
    if 'EV::' in text:
        raise ValueError('无法解析的内部证据编号')
    text=re.sub(r'[（(]\s*[)）]', '',text)
    text=re.sub(r'[,，]\s*([)）])', r'\1',text)
    return text

def prepare_case(case):
    result=copy.deepcopy(case)
    for item in result['canonical'].values():
        if item['text'] is None:
            continue
        if item.get('reconciliation'):
            # An evidence-reviewed revision supersedes archival raw_text.
            # Never resurrect an older canonical sentence during revalidation.
            spoken_text(item['text'],item['evidence_ids'])
            continue
        raw=item.get('raw_text',item['text'])
        text=spoken_text(raw,item['evidence_ids'])
        conflicts=ratio_conflicts(text)
        item['raw_text']=raw
        if conflicts:
            pairs='；'.join(f"{x['percentage']}%与{x['numerator']}/{x['denominator']}不一致" for x in conflicts)
            item['text']='该项表述存在内部数值矛盾。待核对表述为：“'+text.rstrip('。')+'”。其中'+pairs+'，因此这些有冲突的比例暂不用于定量结论，需回到原始研究核对。'
        else:
            item['text']=text
        item['source_warnings']=conflicts
    return result
