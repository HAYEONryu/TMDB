import signal
import threading
from datetime import date
from django.core.management.base import BaseCommand,CommandError
from django.db import connection, close_old_connections
from apps.imports.services import cleanup_imports
from apps.common.receipts import cleanup_p4_receipts,cleanup_mutation_receipts
from apps.operations.scheduler import run_jobs
from apps.ai_assistant.worker import reap


class Command(BaseCommand):
    help = "60초마다 KST 23시/누락 자동 회수와 만료 업로드·요청 결과를 정리합니다."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--retry-date",type=date.fromisoformat,help="해당 날짜 기존 작업을 자동 시도 상한과 관계없이 한 번 재시도합니다. --once 필수")

    def handle(self, *args, **options):
        if options['retry_date'] and not options['once']:raise CommandError('--retry-date는 --once와 함께 사용해 주세요.')
        stopped = threading.Event()
        if not options["once"]:
            signal.signal(signal.SIGTERM, lambda *args: stopped.set())
            signal.signal(signal.SIGINT, lambda *args: stopped.set())
        while True:
            try:
                close_old_connections()
                with connection.cursor() as cursor:cursor.execute('SELECT 1')
                jobs=run_jobs(retry_date=options['retry_date']);result=cleanup_imports();cleanup_p4_receipts();cleanup_mutation_receipts();reap()
                self.stdout.write(f"scheduler: PostgreSQL 정상, 자동 회수 완료 {jobs['completed']}·실패 {jobs['failed']}, 만료 업로드 {result['batches_cleaned']}개 정리.")
                if jobs['failed'] and options['once']:raise CommandError('예약 작업 실패. ScheduledJobRun 상태·오류 코드를 확인해 주세요.')
            except CommandError:raise
            except Exception:
                if options['once']:raise CommandError('예약 점검 실패. DB 연결·시작일 설정·실행 기록을 확인해 주세요.') from None
                self.stderr.write('scheduler: 점검 실패. 다음 주기에 다시 확인합니다.')
            if options["once"] or stopped.wait(60):
                break
