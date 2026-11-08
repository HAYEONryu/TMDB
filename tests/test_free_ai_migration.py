"""Upgrade old AI rows in a disposable database without recreating their data."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from tests.helpers import TEST_HASHERS, user


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class FreeAILimitMigrationTests(TransactionTestCase):
    def test_v5_rows_and_keys_preserved_v6_defaults_paid_and_forty_constraint(self):
        actor=user(initial=False)
        before=[('ai_assistant','0005_openai_request_policy_usage')]
        after=[('ai_assistant','0007_separate_test_budget')]
        executor=MigrationExecutor(connection)
        executor.migrate(before)
        try:
            old=executor.loader.project_state(before).apps
            bucket=old.get_model('ai_assistant','AIQuotaBucket').objects.create(user_id=actor.pk,korean_date='2026-11-07',successful_count=30)
            budget=old.get_model('ai_assistant','AIBudgetMonth').objects.create(month='2026-11-01',charged_usd=Decimal('.25'))
            instant=datetime(2026,11,7,tzinfo=timezone.utc)
            request=old.get_model('ai_assistant','AIRequest').objects.create(actor_id=actor.pk,actor_session_version=1,
                feature='SUMMARY',korean_date='2026-11-07',period_start=instant,period_end=instant,
                scope_key='synthetic',period_key='2026-11-07',idempotency_key=uuid4(),body_hash='old-hash',
                cache_key='old-cache',source_fingerprint='old-source',input_payload={'notes':'가짜 보존 자료'},
                provider='gemini',model_version='gemini-3.8-flash',pricing_version='old-prices',
                input_price=Decimal('.75'),output_price=Decimal('3.75'),input_tokens_cap=16000,
                output_tokens_cap=2048,reasoning_tokens_cap=2048,budget_month_id=budget.pk,quota_bucket_id=bucket.pk,
                reserved_cost=0,charged_cost=0)
            executor=MigrationExecutor(connection);executor.migrate(after)
            current=executor.loader.project_state(after).apps
            upgraded=current.get_model('ai_assistant','AIRequest').objects.get(pk=request.pk)
            self.assertEqual(upgraded.input_payload,{'notes':'가짜 보존 자료'})
            self.assertEqual((upgraded.body_hash,upgraded.cache_key,upgraded.model_version),('old-hash','old-cache','gemini-3.8-flash'))
            self.assertEqual((upgraded.usage_tier,upgraded.provider_day_id,upgraded.provider_sent_at),('paid',None,None))
            new_bucket=current.get_model('ai_assistant','AIQuotaBucket').objects.get(pk=bucket.pk)
            self.assertEqual(new_bucket.successful_count,30)
            new_bucket.successful_count=40;new_bucket.save()
            self.assertEqual(current.get_model('ai_assistant','AIBudgetMonth').objects.get(pk=budget.pk).charged_usd,Decimal('.25'))
        finally:
            MigrationExecutor(connection).migrate(after)
