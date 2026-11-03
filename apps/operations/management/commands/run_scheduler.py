import signal
import threading
from django.core.management.base import BaseCommand
from django.db import connection, close_old_connections


class Command(BaseCommand):
    help = "예약 프로세스 기반. 2단계에서는 연결 점검만 하며 업무 예약은 실행하지 않음."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        stopped = threading.Event()
        if not options["once"]:
            signal.signal(signal.SIGTERM, lambda *args: stopped.set())
            signal.signal(signal.SIGINT, lambda *args: stopped.set())
        while True:
            close_old_connections()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            self.stdout.write("scheduler: PostgreSQL 연결 정상. 업무 예약은 후속 단계에서 구현합니다.")
            if options["once"] or stopped.wait(60):
                break
