"""The acceptance report must never count missing, skipped or stale evidence."""
import io
import json
from unittest import FunctionTestCase

from django.conf import settings
from django.test import SimpleTestCase

from config.acceptance_runner import EvidenceResult
from scripts.verify_acceptance import source_digest, verify


class AcceptanceEvidenceTests(SimpleTestCase):
    def report(self):
        manifest = json.loads((settings.BASE_DIR / "tests/acceptance_basic.json").read_text())
        return {"finished_at": "test-only", "source_digest": source_digest(settings.BASE_DIR),
                "source_unchanged_during_run": True, "successful": True, "tests_run": 0,
                "outcomes": {test: "passed" for row in manifest for test in row["tests"]}}

    def test_missing_skipped_and_failed_evidence_never_passes_all_criteria(self):
        for status in [None, "skipped", "failed", "error", "expected_failure"]:
            report = self.report()
            name = next(iter(report["outcomes"]))
            if status is None: report["outcomes"].pop(name)
            else: report["outcomes"][name] = status
            result = verify(settings.BASE_DIR, report)
            self.assertLess(result["passed"], 69)
            self.assertTrue(any(row["status"] == "incomplete" for row in result["items"]))

    def test_stale_source_or_changed_source_during_run_is_rejected(self):
        for field, value in [("source_digest", "stale"), ("source_unchanged_during_run", False)]:
            report = self.report(); report[field] = value
            with self.assertRaises(AssertionError): verify(settings.BASE_DIR, report)

    def test_subtest_failure_cannot_be_overwritten_by_later_success(self):
        result = EvidenceResult(io.StringIO(), descriptions=False, verbosity=0)
        test = FunctionTestCase(lambda: None)
        result.addSubTest(test, test, (AssertionError, AssertionError("test-only"), None))
        result.addSuccess(test)
        self.assertEqual(result.outcomes[test.id()], "failed")
