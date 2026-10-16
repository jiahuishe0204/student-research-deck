"""Two-layer experiment; does not modify public workflows or saved tasks."""
import argparse
import copy
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from claim_bound_view import canonical_claims, render_bound_page
from model_usage import ModelUsageLedger
from model_routing import ModelRouter
from workflow_service import WorkflowService
from server import load_dotenv
import os

OUT = ROOT / 'artifacts/claim-bound-pilot'
PRIOR_TASK = 'TASK-04316558ac31'
LIVE_TASK = 'PILOT-CLAIM-BOUND-20261016'
CASES = [('TASK-9247d22f42ff', 'SL-09', '记录性能与比较条件'),
         ('TASK-9247d22f42ff', 'SL-10', '电压测量与电荷注入'),
         ('TASK-9247d22f42ff', 'SL-11', '配方形貌与加工条件'),
         (PRIOR_TASK, 'SL-06', '神经电极功能与比较条件')]


def fixtures():
    cases = []
    with sqlite3.connect(f"file:{ROOT / 'data/tasks.sqlite3'}?mode=ro", uri=True) as db:
        for task, pid, title in CASES:
            data = {k: json.loads(v) for k,v in db.execute('SELECT kind,payload_json FROM artifacts WHERE task_id=?', (task,))}
            claims = [c for c in data['claims']['claims'] if c['section_or_page_id'] == pid and c['location_type'].startswith('ppt_')]
            canonical = canonical_claims(claims, data['verification'])
            page = next(p for p in data['ppt']['pages'] if p['page_id'] == pid)
            fig_ids = {f['figure_id'] for f in page['figure_refs']}
            figures = [f for g in data['evidence']['groups'] for f in g['figure_records'] if f['figure_id'] in fig_ids]
            if {f['figure_id'] for f in figures} != fig_ids:
                raise ValueError('原图源无法完整恢复')
            cases.append({'task': task, 'page_id': pid, 'topic_key': title, 'canonical': canonical, 'source_figures': figures})
    return cases


def render(layout, case):
    if layout.get('page_id') != case['page_id'] or layout.get('topic_key') != case['topic_key']:
        raise ValueError('页面或主题错配')
    return render_bound_page(layout, case['canonical'], {case['topic_key']: case['topic_key']}, case['source_figures'])


def write(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def offline():
    outputs = []
    for case in fixtures():
        ids = list(case['canonical'])
        layout = dict(page_id=case['page_id'], topic_key=case['topic_key'], title_claim_ids=[],
                      bullet_claim_ids=ids, note_claim_ids=ids, visual_claim_ids=ids,
                      figure_ids=[f['figure_id'] for f in case['source_figures']])
        page = render(layout, case)
        for value in case['canonical'].values():
            if value['text']:
                assert value['text'].rstrip('。') in page['speaker_notes']
        facts = json.dumps({k: page[k] for k in ('title', 'on_slide_text', 'speaker_notes', 'visual_suggestion')}, ensure_ascii=False)
        if case['task'] == PRIOR_TASK:
            assert '更低阻抗' not in facts and '增强CIC' not in facts and '增强的电荷注入容量' not in facts
        if case['page_id'] == 'SL-10':
            assert '不等同于' in facts and '12 mA' in facts and 'n=1' in facts
        if case['page_id'] == 'SL-11':
            assert '批次间一致性' not in facts
        outputs.append({'input': case, 'layout': layout, 'rendered': page})
    write('offline.json', {'status': 'passed', 'real_cases': 4, 'model_calls': 0, 'outputs': outputs,
                            'scope': 'canonical re-render of saved page claims, not semantic matching of legacy prose'})
    print('OFFLINE: four real cases passed; no model calls')


def live():
    offline()
    cases = [fixtures()[1], fixtures()[3]]
    ledger = ModelUsageLedger(ROOT / 'data/private/model-usage.sqlite3')
    remaining = 2 - ledger.cost_cny(PRIOR_TASK)
    if remaining <= 0:
        raise ValueError('累计预算已耗尽')
    limit = min(0.15, remaining)
    load_dotenv(ROOT.parent / '.env')
    prompt = (ROOT / 'prompts/experimental-claim-layout.md').read_text(encoding='utf-8')
    service = WorkflowService(os.environ.get('DEEPSEEK_API_KEY', ''), ModelRouter.from_file(),
                              '按输入契约输出科研内容布局。不得新增事实。', {'P6': prompt},
                              usage_ledger=ledger, model_limits={'task_max_cost_cny': limit})
    service.set_task_context(LIVE_TASK)
    def validate(value):
        if not isinstance(value, dict) or set(value) != {'pages'} or not isinstance(value['pages'], list) or len(value['pages']) != 2:
            raise ValueError('必须恰好两页布局')
        for layout, case in zip(value['pages'], cases):
            render(layout, case)
        return value
    result, usage, _ = service.generate('P6', 'deep', {'pages': cases}, validate,
                                       max_tokens=1500, max_attempts=1, request_timeout=90)
    pages = [render(layout, case) for layout, case in zip(result['pages'], cases)]
    # A later verdict change must propagate to every bound surface, without a model.
    changed = copy.deepcopy(cases[0])
    cid = next(cid for cid, v in changed['canonical'].items() if v['text'] and '不等同于' in v['text'])
    withdrawn_text = changed['canonical'][cid]['text']
    changed['canonical'][cid]['text'] = None
    updated = render(result['pages'][0], changed)
    assert withdrawn_text not in json.dumps(updated, ensure_ascii=False)
    write('live.json', {'status': 'passed', 'layout': result, 'rendered': pages, 'after_withdrawal': updated,
                        'usage': usage, 'incremental_cost_cny': ledger.cost_cny(LIVE_TASK),
                        'combined_cost_cny': ledger.cost_cny(PRIOR_TASK) + ledger.cost_cny(LIVE_TASK),
                        'scope': 'two newly generated layouts over fixed verified claims; not fresh scientific drafting'})
    print('LIVE: two generated layouts and later withdrawal passed')
    print(json.dumps({'pilot_cost_cny': ledger.cost_cny(LIVE_TASK), 'combined_cost_cny': ledger.cost_cny(PRIOR_TASK) + ledger.cost_cny(LIVE_TASK)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    live() if args.live else offline()
