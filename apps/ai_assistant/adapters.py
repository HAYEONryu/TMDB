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
        if task.schema_version=="admin-v1":
            from .admin_schema import fake
            return ProviderResponse(fake(task),input_tokens=100,output_tokens=50,reasoning_tokens=10,provider_request_id="test-only-"+str(task.pk))
        if task.schema_version=="employee-v1":
            from .employee_schema import FIELDS
            sid=str(task.customer_id); current=payload['current']; quote=current['notes'][:100] if current['notes'] else current['information_state']
            common={'feature':task.feature,'is_test':True,'source_ids':[sid],'limitations':['테스트 전용 가짜 응답입니다. 실제 상담 분석이 아닙니다.']}
            if task.feature=='CLEANUP':
                suggestions={field:{'status':'NO_SUGGESTION','value':None,'source_ids':[],'evidence':'','reason':'근거 부족으로 기존 값을 유지합니다.'} for field in FIELDS}
                if current['notes']:suggestions['notes']={'status':'SUGGESTION','value':'테스트 정리: '+current['notes'],'source_ids':[sid],'evidence':quote,'reason':'테스트용 메모 정리'}
                content={**common,'suggestions':suggestions}
            elif task.feature=='SUMMARY':
                content={**common,'key_points':[{'text':'테스트 요약: '+quote,'source_ids':[sid],'evidence':quote}], 'concerns':[],'promises':[],'checks':[]}
            else:
                content={**common,'questions':[{'question':question,'purpose':purpose,'source_ids':[sid],'evidence':quote} for question,purpose in [('현재 가장 확인하고 싶은 사항은 무엇인가요?','상담 확인점 파악'),('추가로 설명이 필요한 부분이 있나요?','정보 부족 확인'),('다음 연락 시 확인할 사항은 무엇인가요?','후속 확인 순서 정리')]]}
            return ProviderResponse(content,input_tokens=100,output_tokens=50,reasoning_tokens=10,provider_request_id='test-only-'+str(task.pk))
        return ProviderResponse({"feature": task.feature, "text": "테스트 전용 공통 기반 응답입니다. 운영 분석 결과가 아닙니다.",
                                 "source_ids": sorted(source_ids(task.result)), "is_test": True}, input_tokens=100, output_tokens=50, reasoning_tokens=10,
                                provider_request_id="test-only-"+str(task.pk))
