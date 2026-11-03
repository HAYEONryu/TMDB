from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "P1 AI worker 연결 점검. 아직 작업을 생성하거나 AI를 호출하지 않습니다."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        self.stdout.write("AI worker 기반 연결 정상. 생성·외부 호출은 미구현이며 실행하지 않습니다.")
