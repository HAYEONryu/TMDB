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

    def ai_report(self):
        report = self.report()
        manifest = json.loads((settings.BASE_DIR / "tests/acceptance_ai.json").read_text())
        report['outcomes'] = {name: 'passed' for row in manifest for name in row['tests']}
        return report

    def test_ai_criteria_require_actual_boundary_evidence_and_reject_stale_audit(self):
        report = self.ai_report()
        result = verify(settings.BASE_DIR, report, suite='ai')
        self.assertEqual(result['total'], 23)
        self.assertEqual(result['passed'], 22)
        row = next(row for row in result['items'] if row['id'] == '18.8-22')
        self.assertEqual(row['status'], 'incomplete')
        self.assertEqual(row['evidence']['boundary:docker_image_layers'], 'not_run')
        boundary = {'source_digest': 'stale', 'checks': {}}
        with self.assertRaises(AssertionError):
            verify(settings.BASE_DIR, report, suite='ai', boundary=boundary)

    def test_ai_missing_or_skipped_browser_checks_are_not_counted_as_passed(self):
        report = self.ai_report()
        name = 'tests.browser_p12.P12BrowserTests.test_employee_generation_and_encrypted_queue_never_receive_server_key'
        for status in [None, 'skipped', 'failed']:
            if status is None:
                report['outcomes'].pop(name)
            else:
                report['outcomes'][name] = status
            result = verify(settings.BASE_DIR, report, suite='ai')
            self.assertEqual(result['passed'], 21)

    def test_full_92_criteria_do_not_hide_the_missing_docker_item(self):
        report = self.report()
        report['outcomes'].update(self.ai_report()['outcomes'])
        result = verify(settings.BASE_DIR, report, suite='all')
        self.assertEqual((result['total'],result['passed']),(92,91))
        self.assertEqual([row['id'] for row in result['items'] if row['status'] != 'passed'],['18.8-22'])
