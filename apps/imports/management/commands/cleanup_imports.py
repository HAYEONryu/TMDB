from django.core.management.base import BaseCommand
from apps.imports.services import cleanup_imports


class Command(BaseCommand):
    help="만료된 업로드 후보/행 원문(24시간)과 집계 메타데이터(추가7일)를 정리합니다."

    def handle(self,*args,**options):
        total=0
        while True:
            result=cleanup_imports()
            total+=result["batches_cleaned"]
            if result["batches_cleaned"]<50:break
        self.stdout.write(f"업로드 정리: {total}개 batch 처리. 고객정보는 유지했습니다.")
