import signal
import threading
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, close_old_connections
from apps.ai_assistant.worker import run_once


class Command(BaseCommand):
    help = "AI DB 큐 처리. 활성화된 OpenAI 설정에서만 유료 요청하며 fake는 격리 테스트만 허용."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        stopped = threading.Event()
        if not options["once"]:
            signal.signal(signal.SIGTERM, lambda *args: stopped.set())
            signal.signal(signal.SIGINT, lambda *args: stopped.set())
        while True:
            try:
                close_old_connections()
                with connection.cursor() as cursor: cursor.execute("SELECT 1")
                result = run_once()
                self.stdout.write(f"AI worker: PostgreSQL 정상, 처리 {result['processed']}·성공 {result['succeeded']}.")
            except Exception:
                if options["once"]: raise CommandError("AI worker 점검 실패. DB/작업 상태를 확인해 주세요.") from None
                self.stderr.write("AI worker: 점검 실패. 다음 주기에 다시 확인합니다.")
            if options["once"] or stopped.wait(2): break
