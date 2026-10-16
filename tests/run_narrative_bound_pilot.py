"""Experimental author/reviewer calls; no changes to production P6/P9."""
import copy
import json
import os
import sqlite3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.run_claim_bound_pilot import fixtures
from model_usage import ModelUsageLedger
from model_routing import ModelRouter
from workflow_service import WorkflowService
from server import load_dotenv

OUT = ROOT / 'artifacts/narrative-bound-pilot'
TASK = 'PILOT-NARRATIVE-BOUND-20261016'


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def cases():
    selected = [fixtures()[1], fixtures()[3]]
    with sqlite3.connect(f"file:{ROOT / 'data/tasks.sqlite3'}?mode=ro", uri=True) as db:
        for case in selected:
            d = {k:json.loads(v) for k,v in db.execute('SELECT kind,payload_json FROM artifacts WHERE task_id=?',(case['task'],))}
            pages = d['ppt']['pages']
            i = next(i for i,p in enumerate(pages) if p['page_id']==case['page_id'])
            case.update(plan=d['plan'], purpose=pages[i]['purpose'],
                        previous_title=pages[i-1]['title'] if i else '',
                        next_title=pages[i+1]['title'] if i+1<len(pages) else '')
    return selected


def validate_author(value, inputs):
    if set(value) != {'pages'} or len(value['pages']) != len(inputs):
        raise ValueError('页面数量或字段错误')
    rendered=[]
    for p,c in zip(value['pages'],inputs):
        if set(p) != {'page_id','topic_key','segments','figure_choices'} or p['page_id']!=c['page_id'] or p['topic_key']!=c['topic_key']:
            raise ValueError('页面身份或字段错误')
        seen=[]; text=[]
        for seg in p['segments']:
            if set(seg)!={'kind','value'} or not isinstance(seg['value'],str): raise ValueError('片段错误')
            if seg['kind']=='claim':
                cid=seg['value']; fact=c['canonical'].get(cid,{}).get('text')
                if not fact: raise ValueError('未知或撤下的主张')
                seen.append(cid); text.append(fact)
            elif seg['kind']=='bridge': text.append(seg['value'])
            else: raise ValueError('未知片段类型')
        active={cid for cid,v in c['canonical'].items() if v['text']}
        if set(seen)!=active or len(seen)!=len(set(seen)): raise ValueError('有效主张遗漏或重复')
        if len('\n'.join(text))>800: raise ValueError('讲稿过长，不得截断')
        for f in p['figure_choices']:
            if set(f)!={'figure_id','claim_ids','panel','reason'} or f['figure_id'] not in {x['figure_id'] for x in c['source_figures']} or not f['claim_ids'] or not set(f['claim_ids'])<=active:
                raise ValueError('配图结构错误')
        rendered.append(dict(p,speaker_notes='\n'.join(text)))
    return rendered


def validate_review(value, inputs):
    if set(value)!={'reviews'} or len(value['reviews'])!=len(inputs): raise ValueError('审查结果数量错误')
    for r,c in zip(value['reviews'],inputs):
        if set(r)!={'page_id','verdict','issues'} or r['page_id']!=c['page_id'] or r['verdict'] not in ('pass','fail'): raise ValueError('审查字段错误')
        if (r['verdict']=='pass') != (len(r['issues'])==0): raise ValueError('审查结论矛盾')
        for issue in r['issues']:
            if set(issue)!={'location','quote','reason','evidence','repair'} or any(not isinstance(v,str) or not v for v in issue.values()): raise ValueError('审查无具体依据')
    return value


def main():
    inputs=cases(); save('inputs.json',inputs)
    ledger=ModelUsageLedger(ROOT/'data/private/model-usage.sqlite3')
    prior=sum(ledger.cost_cny(t) for t in ['TASK-04316558ac31','PILOT-CLAIM-BOUND-20261016'])
    cap=min(0.15,2-prior)
    if cap<=0: raise ValueError('预算不足')
    load_dotenv(ROOT.parent/'.env')
    service=WorkflowService(os.environ.get('DEEPSEEK_API_KEY',''),ModelRouter.from_file(),'仅按给定材料完成实验，输出JSON。',
        {'P6':(ROOT/'prompts/experimental-narrative-bound.md').read_text(),
         'P8':(ROOT/'prompts/experimental-narrative-review.md').read_text()},usage_ledger=ledger,model_limits={'task_max_cost_cny':cap})
    service.set_task_context(TASK)
    def author_check(v): validate_author(v,inputs); return v
    author,_,_=service.generate('P6','deep',{'cases':inputs},author_check,max_tokens=2200,max_attempts=1,request_timeout=90)
    pages=validate_author(author,inputs); save('author.json',pages)
    print('Author completed',flush=True)
    review,_,_=service.generate('P8','deep',{'cases':inputs,'pages':pages},lambda v:validate_review(v,inputs),max_tokens=2500,max_attempts=1,request_timeout=90)
    save('review.json',review); print('Review completed',flush=True)
    control=copy.deepcopy(pages)
    bad='因此，这项测量证明水凝胶电极的电荷注入效率超过铂电极。'
    control[0]['segments'].append({'kind':'bridge','value':bad}); control[0]['speaker_notes']+='\n'+bad
    control[1]['figure_choices']=[{'figure_id':inputs[1]['source_figures'][0]['figure_id'], 'claim_ids':['CLM-0076'], 'panel':'Figure 3', 'reason':'该图直接证明ICPN电极降低组织反应并改善记录质量。'}]
    save('negative-control.json',control)
    audit,_,_=service.generate('P8','deep',{'cases':inputs,'pages':control},lambda v:validate_review(v,inputs),max_tokens=2500,max_attempts=1,request_timeout=90)
    save('control-review.json',audit)
    summary={'new_cost_cny':ledger.cost_cny(TASK),'combined_cost_cny':prior+ledger.cost_cny(TASK),
             'author_reviews':[r['verdict'] for r in review['reviews']],
             'control_reviews':[r['verdict'] for r in audit['reviews']],
             'production_changed':False,'scope':'two separate case pages; one author and two isolated reviewer calls'}
    save('summary.json',summary); print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__': main()
