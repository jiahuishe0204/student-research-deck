"""Reserved real-topic case; first invoked after development policy freeze."""
import json
import sqlite3
from pathlib import Path
from claim_bound_view import canonical_claims

ROOT=Path(__file__).resolve().parents[1]

def holdout(task='TASK-db61c065ba64'):
    with sqlite3.connect(f"file:{ROOT / 'data/tasks.sqlite3'}?mode=ro",uri=True) as db:
        data={k:json.loads(v) for k,v in db.execute('SELECT kind,payload_json FROM artifacts WHERE task_id=?',(task,))}
    pages=data['ppt']['pages']
    for i,page in enumerate(pages[1:],1):
        claims=[c for c in data['claims']['claims'] if c['section_or_page_id']==page['page_id'] and c['location_type'].startswith('ppt_')]
        registry={e['evidence_id']:e for g in data['evidence']['groups'] for e in g['evidence_records']}
        canonical=canonical_claims(claims,data['verification'],registry)
        active=[v['text'] for v in canonical.values() if v['text']]
        if not 1<=len(active)<=5 or sum(map(len,active))>550:
            continue
        ids={f['figure_id'] for f in page['figure_refs']}
        figures=[f for g in data['evidence']['groups'] for f in g['figure_records'] if f['figure_id'] in ids]
        if {f['figure_id'] for f in figures}!=ids:
            raise ValueError('保留主题图源缺失，不能换页规避')
        return {'task':task,'page_id':page['page_id'],'topic_key':'研究证据与适用边界',
                'purpose':page['purpose'],'canonical':canonical,'source_figures':figures,
                'evidence_sources':{e['evidence_id']:e['source_id'] for g in data['evidence']['groups'] for e in g['evidence_records']},
                'plan':data['plan'],'previous_title':pages[i-1]['title'],
                'next_title':pages[i+1]['title'] if i+1<len(pages) else '',
                'fixture_kind':'saved_research_not_current_medical_advice'}
    raise ValueError('保留主题没有符合预设容量的页面，不自动挑选其他主题')
