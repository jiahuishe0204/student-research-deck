import copy
import unittest
from canonical_reconcile import apply_reconciliation
from canonical_surface import prepare_case

class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.case={'canonical':{'C':{'text':'测试未达极限。','evidence_ids':['E']},'D':{'text':None,'evidence_ids':[]}},
                   'evidence_records':[{'evidence_id':'E','excerpt':'Pt reached limit; gel did not.'}]}
        self.value={'claims':[{'claim_id':'C','action':'revise','text':'Pt已达极限，凝胶未达到。','reason':'区分组别',
                             'citations':[{'evidence_id':'E','quote':'Pt reached limit; gel did not.'}]}]}
    def test_revision_keeps_provenance_and_withdrawal(self):
        result=apply_reconciliation(self.case,self.value)
        self.assertEqual(result['canonical']['C']['prior_canonical'],self.case['canonical']['C'])
        self.assertIsNone(result['canonical']['D']['text'])
        self.assertEqual(self.case['canonical']['C']['text'],'测试未达极限。')
    def test_reprocessing_does_not_restore_archival_error(self):
        prepared=prepare_case(self.case)
        corrected=apply_reconciliation(prepared,self.value)
        self.assertEqual(prepare_case(corrected),corrected)
        self.assertEqual(prepare_case(corrected)['canonical']['C']['text'],'Pt已达极限，凝胶未达到。')
    def test_fabricated_evidence_fails(self):
        self.value['claims'][0]['citations'][0]['quote']='both below limit'
        with self.assertRaisesRegex(ValueError,'原始摘录'): apply_reconciliation(self.case,self.value)
    def test_revision_cannot_only_change_explanation(self):
        self.value['claims'][0]['text']=self.case['canonical']['C']['text']
        with self.assertRaisesRegex(ValueError,'行动'):apply_reconciliation(self.case,self.value)
        self.value['claims'][0]['action']='keep'
        apply_reconciliation(self.case,self.value)
    def test_missing_or_resurrected_claim_fails(self):
        for values in ([],self.value['claims']+[dict(self.value['claims'][0],claim_id='D')]):
            with self.assertRaisesRegex(ValueError,'遗漏或新增'):apply_reconciliation(self.case,{'claims':values})
    def test_conflict_disclosure_cannot_be_removed(self):
        self.case['canonical']['C']['source_warnings']=[{'conflict':True}]
        with self.assertRaisesRegex(ValueError,'矛盾声明'):apply_reconciliation(self.case,self.value)
