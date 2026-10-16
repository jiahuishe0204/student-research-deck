import copy
import unittest
from claim_bound_view import canonical_claims, render_bound_page


class ClaimBoundViewTests(unittest.TestCase):
    def setUp(self):
        self.claims = [{'claim_id': 'A', 'original_text': '电压下降证明效率优于Pt', 'cited_evidence_ids': ['E1']},
                       {'claim_id': 'B', 'original_text': '配方影响形貌', 'cited_evidence_ids': ['E2']}]
        self.results = [{'claim_id': 'A', 'support_status': 'partially_supported', 'action': 'revise',
                         'revised_claim': '固定12 mA、n=1时电压较低，不能据此比较电荷注入效率。', 'valid_evidence_ids': ['E1']},
                        {'claim_id': 'B', 'support_status': 'supported', 'action': 'keep', 'valid_evidence_ids': ['E2']}]
        self.layout = {'page_id': 'P', 'topic_key': 'T', 'title_claim_ids': ['A'], 'bullet_claim_ids': ['A', 'B'],
                       'note_claim_ids': ['A', 'B'], 'visual_claim_ids': ['A'], 'figure_ids': []}
    def render(self):
        return render_bound_page(self.layout, canonical_claims(self.claims, {'results': self.results}), {'T': '电极比较'})
    def test_revision_updates_every_field_and_preserves_other_fact(self):
        output = self.render()
        text = self.results[0]['revised_claim']
        for field in ('title', 'speaker_notes', 'visual_suggestion'):
            self.assertIn(text, output[field])
        self.assertIn(text, output['on_slide_text'])
        self.assertIn('配方影响形貌', output['speaker_notes'])
        self.assertNotIn('效率优于', str(output))
    def test_removal_updates_every_field_without_blank_page(self):
        self.results[0].update(action='remove', support_status='unsupported')
        output = self.render()
        self.assertNotIn('电压', str(output))
        self.assertEqual(output['title'], '电极比较')
        self.assertEqual(output['on_slide_text'], ['配方影响形貌'])
    def test_unbound_paraphrase_rejected(self):
        self.layout['speaker_notes'] = '其注入能力超过铂电极'
        with self.assertRaisesRegex(ValueError, '自由文本'): self.render()
    def test_unknown_id_rejected(self):
        self.layout['visual_claim_ids'] = ['X']
        with self.assertRaisesRegex(ValueError, '未知主张'): self.render()
    def test_coverage_missing_rejected(self):
        self.layout['note_claim_ids'] = ['A']
        with self.assertRaisesRegex(ValueError, '遗漏'): self.render()
    def test_no_valid_citation_rejected(self):
        self.results[0]['valid_evidence_ids'] = ['OTHER']
        with self.assertRaisesRegex(ValueError, '原引用'): self.render()
    def test_revision_citation_migration_is_explicit_and_source_checked(self):
        self.results[0].update(valid_evidence_ids=['E1', 'E3'], source_identity={'source_ids':['S']})
        registry={'E3':{'source_id':'S'}}
        result=canonical_claims(self.claims,{'results':self.results},registry)
        self.assertEqual(result['A']['evidence_ids'],['E1','E3'])
        self.assertEqual(result['A']['citation_migration']['added_verified_ids'],['E3'])
        for invalid in ({},{'E3':{'source_id':'OTHER'}}):
            with self.assertRaisesRegex(ValueError,'修订引用'):
                canonical_claims(self.claims,{'results':self.results},invalid)
        self.assertEqual(canonical_claims(self.claims,{'results':self.results})['A']['evidence_ids'],['E1'])
    def test_truncated_verified_sentence_rejected(self):
        self.results[0]['revised_claim'] = '测量结果，'
        with self.assertRaisesRegex(ValueError, '不完整'): self.render()
    def test_capacity_cannot_be_solved_by_silent_truncation(self):
        self.results[0]['revised_claim'] = '实验条件完整保留' * 150
        with self.assertRaises(ValueError): self.render()
    def test_figures_preserved_exactly_or_rejected(self):
        figure = {'figure_id': 'F1', 'caption': 'Figure 1. (a) response (b) control', 'reuse_status': 'unknown'}
        canonical = canonical_claims(self.claims, {'results': self.results})
        with self.assertRaisesRegex(ValueError, '图源遗漏'):
            render_bound_page(self.layout, canonical, {'T': '电极比较'}, [figure])
        self.layout['figure_ids'] = ['F1']
        output = render_bound_page(self.layout, canonical, {'T': '电极比较'}, [figure])
        self.assertEqual(output['source_figures'], [figure])
        self.assertIsNot(output['source_figures'][0], figure)
