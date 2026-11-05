from django.conf import settings
from django.db import connection


class FakeAIAdapter:
    """Only a test seam in P1. No real provider adapter or network transport."""
    def execute(self, feature):
        if not settings.TESTING or not connection.settings_dict["NAME"].startswith("test_tm_"):
            raise RuntimeError("Fake AI requires test settings and a disposable test database")
        if feature not in {"CLEANUP", "SUMMARY", "NEXT_QUESTIONS"}:
            raise ValueError("Unknown test feature")
        return {"is_test": True, "feature": feature, "text": "테스트 전용 가짜 응답", "provider_calls": 0}


class FoundationFakeAdapter:
    def execute_task(self, task, payload):
        from .services import test_mode
        from .worker import ProviderResponse
        from .inputs import source_ids
        if not test_mode() or not task.is_test:
            raise RuntimeError("Foundation fake requires explicit test settings and disposable test DB")
        return ProviderResponse({"feature": task.feature, "text": "테스트 전용 공통 기반 응답입니다. 운영 분석 결과가 아닙니다.",
                                 "source_ids": sorted(source_ids(task.result)), "is_test": True}, input_tokens=100, output_tokens=50, reasoning_tokens=10,
                                provider_request_id="test-only-"+str(task.pk))
