import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from narrative_links import bind_links,LINKS
from narrative_contract import validate_author
from narrative_review_gate import units,normalize_envelope
from tests.run_narrative_loop import generate_cases

class LoopRoutingTests(unittest.TestCase):
    def setUp(self):
        self.case=bind_links({'page_id':'P','topic_key':'测量条件','canonical':{'C':{'text':'旧条件。','evidence_ids':['E']}},
            'evidence_sources':{'E':'S'},'source_figures':[], 'evidence_records':[{'evidence_id':'E','source_id':'S','excerpt':'source'}]})
        self.page={'page_id':'P','topic_key':'测量条件','figure_choices':[],
            'segments':[{'kind':'bridge','value':LINKS[0]},{'kind':'claim','value':'C'},{'kind':'bridge','value':LINKS[-1]}]}
    def test_free_scientific_bridge_is_rejected_before_model_review(self):
        for bad in ('因此该材料优于铂。','预后价值未定直接影响谁能被纳入治疗。','这说明A导致B。'):
            page=copy.deepcopy(self.page);page['segments'][0]['value']=bad
            with self.assertRaisesRegex(ValueError,'转场'):validate_author({'pages':[page]},[self.case])
        validate_author({'pages':[self.page]},[self.case])
    def test_only_approved_adjacent_links_compacted_not_claims_or_unknown_text(self):
        page=copy.deepcopy(self.page)
        page['segments'].append({'kind':'bridge','value':LINKS[3]})
        clean=normalize_envelope({'pages':[page]},[self.case])['pages'][0]
        self.assertEqual(len(clean['segments']),3)
        self.assertEqual(clean['segments'][1],self.page['segments'][1])
        page['segments'].append({'kind':'bridge','value':'unsupported claim'})
        with self.assertRaises(ValueError):validate_author(normalize_envelope({'pages':[page]},[self.case]),[self.case])
    def test_claim_error_routes_upstream_and_updates_rendered_text(self):
        calls=[]
        def reviewer(service,case,page,directory,label):
            checks=[{'location':u['location'],'status':'pass','quote':'','reason':'检查通过','evidence':'E','repair':''} for u in units(case,page)]
            if case['canonical']['C']['text']=='旧条件。':checks[1].update(status='fail',quote='旧条件。',repair='修正条件归属')
            return {'checks':checks}
        def reconcile(service,directory,label,case,prompts,findings):
            calls.append(findings)
            fixed=copy.deepcopy(case);fixed['canonical']['C']['text']='新条件。'
            return fixed
        def author(*args,**kwargs):return args[7]({'pages':[copy.deepcopy(self.page)]}),{},{}
        with tempfile.TemporaryDirectory() as temp,patch('tests.run_narrative_loop.review',side_effect=reviewer),patch('tests.run_narrative_loop.reconcile_case',side_effect=reconcile),patch('tests.run_narrative_loop.metered',side_effect=author):
            outcomes=generate_cases(None,Path(temp),[self.case],{},[self.page])
            self.assertTrue(outcomes[0]['passed']);self.assertEqual(outcomes[0]['attempts'],2)
            self.assertEqual(len(calls),1)
            self.assertIn('新条件。',(Path(temp)/'case-0-attempt-2.json').read_text())
