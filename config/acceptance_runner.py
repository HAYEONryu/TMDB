"""Optional P8 runner: records outcomes without storing fixture values/tracebacks."""
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import TextTestResult

from django.conf import settings
from django.test.runner import DiscoverRunner

from scripts.verify_acceptance import source_digest


class EvidenceResult(TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes.setdefault(test.id(), "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes[test.id()] = "failed"

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes[test.id()] = "error"

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes[test.id()] = "skipped"

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.outcomes[test.id()] = "expected_failure"

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.outcomes[test.id()] = "unexpected_success"

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.outcomes[test.id()] = "failed"


class AcceptanceRunner(DiscoverRunner):
    @classmethod
    def add_arguments(cls, parser):
        super().add_arguments(parser)
        parser.add_argument("--evidence-label", choices=["p8","p9","p10","p11","p12","p13"], default="p8")

    def __init__(self, *args, evidence_label="p8", **kwargs):
        super().__init__(*args, **kwargs)
        self.evidence_label = evidence_label

    def get_resultclass(self):
        return EvidenceResult

    def run_suite(self, suite, **kwargs):
        root = Path(settings.BASE_DIR)
        before = source_digest(root)
        result = super().run_suite(suite, **kwargs)
        report = {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "source_digest": before,
            "source_unchanged_during_run": before == source_digest(root),
            "tests_run": result.testsRun,
            "successful": result.wasSuccessful(),
            "outcomes": dict(sorted(result.outcomes.items())),
        }
        path = root / f".local/{self.evidence_label}-test-results.json"
        path.parent.mkdir(exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)
        return result
