from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from apps.accounts.models import User
from apps.accounts.services import INITIAL_PASSWORD
from apps.common.transactions import business_write
from apps.common.validation import normalize_phone
from apps.operations.models import OperationEvent
from django.utils import timezone


class Command(BaseCommand):
    help = "최초 업무 관리자 생성. 초기 비밀번호 dodream, 첫 변경 필수."

    def add_arguments(self, parser):
        parser.add_argument("--phone")
        parser.add_argument("--name")

    def handle(self, *args, **options):
        phone = options["phone"] or input("관리자 전화번호: ")
        name = options["name"] or input("관리자 이름: ")
        try:
            phone = normalize_phone(phone)
            with business_write():
                if User.objects.filter(role=User.Role.ADMIN, is_active=True).exists():
                    raise CommandError("활성 관리자가 이미 있습니다. 최초 생성 명령은 추가 관리자 생성에 사용하지 않습니다.")
                user = User.objects.create_user(phone, name, INITIAL_PASSWORD, role=User.Role.ADMIN)
                OperationEvent.objects.create(actor=user, operation="INITIAL_ADMIN_CREATED", occurred_at=timezone.now(), affected_count=1)
        except ValidationError as exc:
            raise CommandError("입력값이 올바르지 않거나 전화번호가 중복됩니다.") from exc
        self.stdout.write(self.style.SUCCESS(f"최초 관리자를 생성했습니다. ID={user.pk}. 첫 로그인에서 비밀번호를 변경하세요."))
