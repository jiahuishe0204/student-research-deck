import unittest

from retrieval import classify_publication_level, merge_source_records
from research_sources import plan_patsnap_queries


class SourceCanonicalizationTests(unittest.TestCase):
    def test_same_doi_merges_and_preserves_each_database_locator(self):
        records = merge_source_records([
            {"source": "Crossref", "source_id": "DOI:10.1234/ABC", "doi": "https://doi.org/10.1234/ABC",
             "title": "Study title", "authors": ["A Person"], "year": "2024", "access": "metadata", "url": "https://crossref.example"},
            {"source": "Europe PMC", "source_id": "MED:1", "doi": "10.1234/abc", "pmid": "123",
             "title": "Study title", "authors": ["A Person"], "year": "2024", "abstract": "Long abstract",
             "access": "full_text", "pmcid": "PMC1", "url": "https://pmc.example"},
        ])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source"], "Europe PMC")
        self.assertEqual(records[0]["reading_scope"], "full_text")
        self.assertEqual({item["source"] for item in records[0]["source_records"]}, {"Crossref", "Europe PMC"})
        self.assertEqual(records[0]["canonical_identity"], "doi:10.1234/abc")

    def test_pmid_bridges_a_record_without_doi_and_duplicate_provenance_survives(self):
        records = merge_source_records([
            {"source": "PubMed", "source_id": "PMID:123", "pmid": "123", "doi": "", "title": "Study", "authors": "A Person", "year": "2024"},
            {"source": "Patsnap", "source_id": "PATSNAP:PAPER:p1", "pmid": "123", "doi": "", "title": "Study", "authors": ["A Person"], "year": "2024"},
        ])
        self.assertEqual(len(records), 1)
        self.assertEqual({item["source"] for item in records[0]["source_records"]}, {"PubMed", "Patsnap"})

    def test_trial_and_patent_family_identity(self):
        trial = merge_source_records([
            {"source": "ClinicalTrials.gov", "source_id": "registry:1", "trial_id": "NCT01234567", "title": "Trial"},
            {"source": "ClinicalTrials.gov", "source_id": "registry:2", "nct_id": "nct01234567", "title": "Different registry title"},
        ])
        patents = merge_source_records([
            {"source": "EPO patent", "source_id": "EP:1", "patent_family_id": "fam-7", "title": "Patent A"},
            {"source": "Patent database", "source_id": "WO:1", "family_id": "FAM-7", "title": "Patent B"},
        ])
        self.assertEqual(len(trial), 1)
        self.assertEqual(trial[0]["canonical_identity"], "trial:NCT01234567")
        self.assertEqual(len(patents), 1)
        self.assertEqual(patents[0]["canonical_identity"], "patent-family:FAM-7")

    def test_conflicting_doi_does_not_merge_by_same_title(self):
        records = merge_source_records([
            {"source": "PubMed", "source_id": "PMID:1", "doi": "10.1/a", "title": "Identical title", "authors": ["A Person"], "year": "2024"},
            {"source": "Crossref", "source_id": "DOI:10.1/b", "doi": "10.1/b", "title": "Identical title", "authors": ["A Person"], "year": "2024"},
        ])
        self.assertEqual(len(records), 2)

    def test_patsnap_query_is_short_and_not_boolean(self):
        plan = {"search_concepts": {"core_terms": ["CAR T cell", "solid tumor"], "mechanism": ["tumor microenvironment"]}}
        queries = plan_patsnap_queries(plan, "fallback")
        self.assertEqual(queries, ["CAR T cell", "solid tumor"])
        self.assertFalse(any("AND" in query or "OR" in query for query in queries))

    def test_publication_level_uses_explicit_types_and_does_not_guess(self):
        self.assertEqual(classify_publication_level({"source": "PubMed", "publication_types": ["Clinical Trial"]}), "primary")
        self.assertEqual(classify_publication_level({"source": "PubMed", "publication_types": ["Review"]}), "secondary")
        self.assertEqual(classify_publication_level({"source": "Patsnap", "title": "Drug target association"}), "primary_or_secondary_unclassified")


if __name__ == "__main__":
    unittest.main()
