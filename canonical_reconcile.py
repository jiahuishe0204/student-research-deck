"""Auditable evidence-bounded corrections before narrative generation."""
import copy
from canonical_surface import spoken_text, ratio_conflicts

def apply_reconciliation(case, value):
    active={k:v for k,v in case['canonical'].items() if v['text']}
    records={e['evidence_id']:e for e in case['evidence_records']}
    if not isinstance(value,dict) or set(value)!={'claims'} or not isinstance(value['claims'],list):
        raise ValueError('底稿修订结构错误')
    ids=[x.get('claim_id') for x in value['claims']]
    if set(ids)!=set(active) or len(ids)!=len(set(ids)):
        raise ValueError('底稿修订遗漏或新增主张')
    result=copy.deepcopy(case)
    for item in value['claims']:
        if set(item)!={'claim_id','text','reason','citations'} or not all(isinstance(item[k],str) and item[k].strip() for k in ('text','reason')) or not item['citations']:
            raise ValueError('底稿修订缺少依据')
        old=active[item['claim_id']]
        if old.get('source_warnings') and item['text']!=old['text']:
            raise ValueError('不得移除来源矛盾声明')
        cited=[]
        for cite in item['citations']:
            record=records.get(cite.get('evidence_id'))
            if not record or not cite.get('quote') or cite['quote'] not in record.get('excerpt',''):
                raise ValueError('修订依据不是原始摘录')
            cited.append(cite['evidence_id'])
        text=spoken_text(item['text'],cited)
        if text.endswith(('，','、',':','：')) or (ratio_conflicts(text) and not old.get('source_warnings')):
            raise ValueError('修订引入截断或数值矛盾')
        target=result['canonical'][item['claim_id']]
        target.update(text=text,evidence_ids=sorted(set(cited)),prior_canonical=copy.deepcopy(old),reconciliation=copy.deepcopy(item))
    return result
