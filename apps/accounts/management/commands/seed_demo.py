from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.accounts.models import User
from apps.accounts.services import INITIAL_PASSWORD
from apps.common.transactions import business_write

DEMO_USERS = [
    ("01000000001", "가상관리자", User.Role.ADMIN),
    ("01000000002", "가상직원가", User.Role.EMPLOYEE),
    ("01000000003", "가상직원나", User.Role.EMPLOYEE),
]


class Command(BaseCommand):
    help = "로컬 가짜 관리자·직원 계정만 생성. 기존 계정/비밀번호는 변경하지 않음."

    def handle(self, *args, **options):
        if not settings.ALLOW_DEMO_SEED:
            raise CommandError("가짜 계정 생성은 ALLOW_DEMO_SEED=true인 개발 환경에서만 가능합니다.")
        with business_write():
            for phone, name, role in DEMO_USERS:
                user = User.objects.filter(phone_normalized=phone).first()
                if user:
                    if user.name != name or user.role != role:
                        raise CommandError("예제 전화번호와 충돌하는 계정이 있어 변경하지 않았습니다.")
                    state = "기존 유지"
                else:
                    user = User.objects.create_user(phone, name, INITIAL_PASSWORD, role=role)
                    state = "생성"
                self.stdout.write(f"{state}: {role} {phone} {user.pk}")
        self.stdout.write(self.style.SUCCESS("가짜 계정 준비 완료. 신규 계정은 첫 로그인에서 비밀번호 변경이 필요합니다."))
