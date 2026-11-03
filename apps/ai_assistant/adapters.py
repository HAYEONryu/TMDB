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
