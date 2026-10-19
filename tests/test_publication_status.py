import unittest
from unittest.mock import patch

import build


class AcceptedPublicationTests(unittest.TestCase):
    def setUp(self):
        self.site = {"me": ["Fan Tang"], "publications": {"merge_before": 2019}}
        self.venues = {
            "cvmj": {"key": "CVMJ", "label": "CVMJ", "name": "Computational Visual Media",
                     "type": "journal", "rank": "", "order": 0},
        }
        self.accepted = {
            "title": "A Music Survey", "authors": ["Fan Tang"], "venue": "CVMJ",
            "id": "music-survey", "publication_status": "accepted_unpublished",
            "bibtex": "@unpublished{survey, title={A Music Survey}, author={Tang, Fan}}",
        }

    def load(self, rows):
        report = build.Report()
        with patch.object(build, "load_yaml", return_value=rows):
            papers = build.load_papers(report, self.site, self.venues)
        return papers, report

    def test_accepted_without_publication_year_is_listed_separately(self):
        papers, report = self.load([self.accepted])
        self.assertEqual(report.errors, [])
        self.assertIsNone(papers[0]["year"])
        groups = build.group_papers(papers, self.site)
        self.assertEqual([g["id"] for g in groups], ["accepted"])
        self.assertEqual(groups[0]["papers"][0]["id"], "music-survey")

    def test_acceptance_confirmation_year_cannot_be_used_as_publication_year(self):
        for fields in ({"year": 2026}, {"bibtex": self.accepted["bibtex"][:-1] + ", year={2026}}"}):
            with self.subTest(fields=fields):
                _, report = self.load([{**self.accepted, **fields}])
                self.assertTrue(any("year" in error for error in report.errors))

    def test_formal_publication_keeps_anchor_and_moves_to_its_year(self):
        row = {**self.accepted, "publication_status": "published", "year": 2027,
               "bibtex": "@article{survey, title={A Music Survey}, author={Tang, Fan}, year={2027}}"}
        papers, report = self.load([row])
        self.assertEqual(report.errors, [])
        groups = build.group_papers(papers, self.site)
        self.assertEqual([g["id"] for g in groups], ["y2027"])
        self.assertEqual(groups[0]["papers"][0]["id"], "music-survey")

    def test_regular_papers_still_require_publication_year(self):
        _, report = self.load([{**self.accepted, "publication_status": "published"}])
        self.assertTrue(any("year" in error for error in report.errors))

    def test_hidden_paper_is_absent_from_groups_and_display_count(self):
        papers, report = self.load([{**self.accepted, "hidden": True}])
        self.assertEqual(report.errors, [])
        self.assertEqual(len(papers), 0)
        self.assertEqual(build.group_papers(papers, self.site), [])


if __name__ == "__main__":
    unittest.main()
