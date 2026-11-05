from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from apps.accounts.models import User
from apps.common.transactions import business_write
from apps.common.validation import site_name_key
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.services import snapshot
from apps.sites.models import Site
from apps.sites.services import change_default, locked_settings


class Command(BaseCommand):
    help = "개발 환경에 가상 현장·미할당 고객 65건 생성. 기존 고객·계정·상담정보 보존."

    def handle(self, *args, **options):
        if not settings.ALLOW_DEMO_SEED:
            raise CommandError("ALLOW_DEMO_SEED=true인 개발 환경에서만 가능합니다.")
        with business_write():
            actor = User.objects.select_for_update().filter(phone_normalized="01000000001", name="가상관리자", role="ADMIN", is_active=True).first()
            if not actor:
                raise CommandError("먼저 seed_demo로 가상관리자 계정을 준비해 주세요.")
            global_settings = locked_settings()
            first = not Site.objects.exists()
            site, _ = Site.objects.get_or_create(name_key=site_name_key("가상현장 · 연습용"), defaults={"name":"가상현장 · 연습용", "created_by":actor})
            if first:
                change_default(global_settings, site, actor, timezone.now())
            created = 0
            for i in range(1, 66):
                customer, new = Customer.objects.get_or_create(site=site, phone_normalized=f"0109000{i:04}", defaults={
                    "customer_name":f"가상고객{i:03}", "notes":"연습용 가짜 자료입니다." if i % 3 == 0 else "",
                    "housing_status":["", "전세", "자가", "월세"][i % 4]})
                if new:
                    ConsultationRevision.objects.create(customer=customer, actor=None, customer_version=customer.version,
                        source="BASELINE", before_values={}, after_values=snapshot(customer, None), notes=customer.notes)
                    created += 1
        self.stdout.write(self.style.SUCCESS(f"가상 현장 고객 {created}건 생성, 기존 데이터 유지. 할당·과거 업무 이력은 생성하지 않았습니다."))
