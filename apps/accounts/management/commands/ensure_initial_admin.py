from django.core.management.base import BaseCommand

from apps.accounts.bootstrap import ensure_initial_admin


class Command(BaseCommand):
    help = "계정이 하나도 없는 DB에 최초 관리자 admin을 생성합니다. 기존 계정과 비밀번호는 보존합니다."

    def handle(self, *args, **options):
        created = ensure_initial_admin()
        self.stdout.write("최초 관리자 생성 완료. 첫 로그인에서 비밀번호 변경이 필요합니다."
                          if created else "기존 계정이 있어 최초 관리자 생성을 생략했습니다.")
