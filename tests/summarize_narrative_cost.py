"""Read-only fee attribution from per-call receipts and durable usage ledger."""
import collections
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model_usage import ModelUsageLedger

def summarize():
    categories=collections.defaultdict(lambda:{'requests':0,'ledger_attempts':0,'cost_cny':0.0})
    rounds={};failures=[];retry_cost=0.0;seen=set()
    for directory in sorted((ROOT/'artifacts/narrative-loop').iterdir()):
        receipts=list(directory.glob('*-cost.json'))
        if not receipts:continue
        total=0.0
        for path in receipts:
            item=json.loads(path.read_text())
            if seen.intersection(item['ledger_ids']):raise ValueError('重复账本编号')
            seen.update(item['ledger_ids'])
            c=categories[item['category']];c['requests']+=1;c['ledger_attempts']+=len(item['ledger_ids']);c['cost_cny']+=item['cost_cny']
            total+=item['cost_cny']
            match=re.search(r'-attempt-(\d+)-',path.name)
            if match and int(match.group(1))>1:retry_cost+=item['cost_cny']
            if item['outcome']=='failed':failures.append({'round':directory.name,'receipt':path.name,'cost_cny':item['cost_cny']})
        summary=directory/'summary.json'
        rounds[directory.name]={'requests':len(receipts),'cost_cny':total,
            'passed':json.loads(summary.read_text())['all_passed'] if summary.exists() else None,
            'status':'completed' if summary.exists() else 'failed' if (directory/'failure.json').exists() else 'running'}
    ledger=ModelUsageLedger(ROOT/'data/private/model-usage.sqlite3')
    with ledger.connect() as db:
        rejected=[dict(r) for r in db.execute('SELECT id,stage,status,prompt_tokens,completion_tokens FROM model_usage WHERE task_id=?',('PILOT-NARRATIVE-LOOP-20261016',)) if r['id'] in seen and r['status']!='accepted']
    total=sum(ledger.cost_cny(t) for t in ['TASK-04316558ac31','PILOT-CLAIM-BOUND-20261016','PILOT-NARRATIVE-BOUND-20261016','PILOT-NARRATIVE-LOOP-20261016'])
    incremental=sum(x['cost_cny'] for x in categories.values())
    if abs(total-1.932636-incremental)>0.000001:raise ValueError('增量账目与累计账目不一致')
    return {'accounting_basis':'Local ledger estimate from returned usage and configured time-of-day rates; not provider invoice or balance.',
            'baseline_before_budget_extension_cny':1.932636,'total_cny':total,'incremental_cny':incremental,
            'budget_cny':3,'categories':dict(categories),'rounds':rounds,'failed_calls':failures,
            'nonaccepted_ledger_attempts':rejected,
            'attempt_2_or_later_cost_cny':retry_cost,
            'note':'Repeated whole rounds are in round totals, not all in attempt_2_or_later. Semantic review failure is billable success at API level. No model calls in this report.'}

if __name__=='__main__':print(json.dumps(summarize(),ensure_ascii=False,indent=2))
