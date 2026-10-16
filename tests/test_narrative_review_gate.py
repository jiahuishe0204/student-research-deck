import copy
import unittest
from narrative_review_gate import render,units,validate_checks,seal,validate_seal,normalize_envelope

class NarrativeReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.case={'page_id':'P','topic_key':'观察与解释','canonical':{'C':{'text':'本样本存在相关性，不能据此推断因果。','evidence_ids':['E']}},'source_figures':[], 'evidence_sources':{'E':'S'}}
        self.page={'page_id':'P','topic_key':'观察与解释','segments':[{'kind':'bridge','value':'这个观察能回答什么问题？'},{'kind':'claim','value':'C'},{'kind':'bridge','value':'下一步需要区分观察与解释。'}],'figure_choices':[]}
        self.review={'checks':[{'location':u['location'],'status':'pass','quote':'','reason':'符合','evidence':'C','repair':''} for u in units(self.case,self.page)]}
    def test_no_figure_is_valid(self):
        self.assertTrue(seal(self.case,self.page,self.review,'v1'))
    def test_harmless_format_repair_does_not_remove_unknown_text(self):
        page=copy.deepcopy(self.page);page.pop('figure_choices')
        raw={'type':'json_object','pages':[page]}
        fixed=normalize_envelope(raw,[self.case])
        self.assertEqual(fixed,{'pages':[self.page]})
        self.assertIn('type',raw)
        raw['unbound_fact']='unsupported'
        self.assertIn('unbound_fact',normalize_envelope(raw,[self.case]))
    def test_missing_figure_field_not_inferred_when_candidates_exist(self):
        case=copy.deepcopy(self.case);case['source_figures']=[{'figure_id':'F'}]
        page=copy.deepcopy(self.page);page.pop('figure_choices')
        self.assertNotIn('figure_choices',normalize_envelope({'pages':[page]},[case])['pages'][0])
    def test_missing_check_rejected(self):
        self.review['checks'].pop()
        with self.assertRaisesRegex(ValueError,'遗漏'): validate_checks(self.review,units(self.case,self.page))
    def test_fabricated_quote_rejected(self):
        self.review['checks'][0].update(status='fail',quote='不存在的句子',repair='删除')
        with self.assertRaisesRegex(ValueError,'真实文字'): validate_checks(self.review,units(self.case,self.page))
    def test_changed_claim_invalidates_every_cached_bridge_review(self):
        approval=seal(self.case,self.page,self.review,'v1')
        self.case['canonical']['C']['text']='新核验句。'
        with self.assertRaisesRegex(ValueError,'失效'): validate_seal(self.case,self.page,approval,'v1')
    def test_changed_policy_invalidates_review(self):
        approval=seal(self.case,self.page,self.review,'v1')
        with self.assertRaisesRegex(ValueError,'失效'): validate_seal(self.case,self.page,approval,'v2')
    def test_changed_figure_or_framework_invalidates_review(self):
        approval=seal(self.case,self.page,self.review,'v1')
        for key,value in [('plan',{'question':'其他问题'}),('source_figures',[{'caption':'Changed'}])]:
            modified=copy.deepcopy(self.case);modified[key]=value
            with self.assertRaisesRegex(ValueError,'失效'): validate_seal(modified,self.page,approval,'v1')
    def test_wrong_source_cannot_pass_with_a_model_approval(self):
        self.case['source_figures']=[{'figure_id':'F','source_id':'OTHER'}]
        self.page['figure_choices']=[{'figure_id':'F','claim_ids':['C'],'panel':'a','reason':'相关性'}]
        with self.assertRaisesRegex(ValueError,'来源不匹配'): render(self.case,self.page)
