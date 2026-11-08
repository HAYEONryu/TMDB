"""Optional P8 runner: records outcomes without storing fixture values/tracebacks."""
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from unittest import TextTestResult

from django.conf import settings
from django.test.runner import DiscoverRunner

from scripts.verify_acceptance import source_digest
from scripts.verification_evidence import RunRecord,run_directory,write_new


class EvidenceResult(TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}
        self.diagnostics = {}

    def startTest(self,test):
        os.environ['TM_EVIDENCE_TEST_ID']=test.id()
        super().startTest(test)

    def _exc_info_to_string(self,err,test):
        # unittest's default output contains source lines, assertion values and
        # browser error snapshots. Never retain those as verification evidence.
        kind=err[0].__name__
        frames=[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name}
                for frame in traceback.extract_tb(err[2]) if str(settings.BASE_DIR) in frame.filename]
        identity=getattr(test,'test_case',test).id()
        self.diagnostics[identity]={'type':kind,'locations':frames}
        return json.dumps(self.diagnostics[identity])+'\n'

    def stopTest(self,test):
        directory=run_directory()
        if directory:
            row={'run_id':directory.name,'test_id':test.id(),'status':self.outcomes.get(test.id(),'incomplete')}
            with (directory/'test-events.jsonl').open('a') as handle:handle.write(json.dumps(row)+'\n')
        super().stopTest(test)

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
        parser.add_argument("--evidence-label", choices=["p8","p9","p10","p11","p12","p13","final"], default="p8")

    def __init__(self, *args, evidence_label="p8", **kwargs):
        super().__init__(*args, **kwargs)
        self.evidence_label = evidence_label

    def get_resultclass(self):
        return EvidenceResult

    def run_tests(self,test_labels,**kwargs):
        self.owned_record=None
        if run_directory() is None:
            self.owned_record=RunRecord(self.evidence_label,['manage.py','test',*(test_labels or [])])
            os.environ['TM_EVIDENCE_RUN_DIR']=str(self.owned_record.path)
        code=1
        try:
            failures=super().run_tests(test_labels,**kwargs)
            code=0 if failures==0 else 1
            return failures
        finally:
            if self.owned_record:
                self.owned_record.finish(code)
                os.environ.pop('TM_EVIDENCE_RUN_DIR',None)

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
            "diagnostics":result.diagnostics,
            "run_id":run_directory().name,
        }
        write_new(run_directory()/'results.json',report)
        return result
