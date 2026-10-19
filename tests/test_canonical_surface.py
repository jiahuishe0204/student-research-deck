import unittest
from canonical_surface import ratio_conflicts,spoken_text,prepare_case

class CanonicalSurfaceTests(unittest.TestCase):
    def test_actual_conflict_detected_without_guessing_correct_source_value(self):
        self.assertEqual(len(ratio_conflicts('38.7%（334/686）')),1)
    def test_rounding_not_falsely_flagged(self):
        for text in ('52%（135/262）','48.7% (334/686)','50.0%（1/2）'):
            self.assertEqual(ratio_conflicts(text),[])
    def test_zero_denominator_flagged(self):
        self.assertEqual(len(ratio_conflicts('50%（1/0）')),1)
    def test_threshold_not_treated_as_observed_percentage(self):
        self.assertEqual(ratio_conflicts('≥40%（334/686）'),[])
    def test_evidence_removed_only_from_spoken_surface(self):
        raw='样本量（n=3，EV::PMID:1::001）。'
        self.assertEqual(spoken_text(raw,['EV::PMID:1::001']),'样本量（n=3）。')
        with self.assertRaisesRegex(ValueError,'未核验'):spoken_text(raw,[])
    def test_disclosure_preserves_original_and_is_idempotent(self):
        case={'canonical':{'C':{'text':'文献报告38.7%（334/686）为阳性。','evidence_ids':['E']}}}
        prepared=prepare_case(case)
        self.assertIn('暂不用于定量结论',prepared['canonical']['C']['text'])
        self.assertIn('待核对表述',prepared['canonical']['C']['text'])
        self.assertNotIn('来源记载',prepared['canonical']['C']['text'])
        self.assertEqual(prepared['canonical']['C']['raw_text'],case['canonical']['C']['text'])
        self.assertEqual(prepare_case(prepared),prepared)
        self.assertNotIn('暂不',case['canonical']['C']['text'])
