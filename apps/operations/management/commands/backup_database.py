import json
import os
from django.core.management.base import BaseCommand, CommandError
from apps.operations.backups import BackupError, create_backup


class Command(BaseCommand):
    help = 'Stream pg_dump through age, verify delivery, then apply backup retention.'

    def add_arguments(self, parser):
        parser.add_argument('--directory', default=os.environ.get('BACKUP_DIRECTORY'))
        parser.add_argument('--destination', default=os.environ.get('BACKUP_DESTINATION'))
        parser.add_argument('--recipient', default=os.environ.get('BACKUP_RECIPIENT'))
        parser.add_argument('--retention-days', type=int, default=os.environ.get('BACKUP_RETENTION_DAYS', '7'))

    def handle(self, *args, **options):
        if not all(options[k] for k in ['directory', 'destination', 'recipient']):
            raise CommandError('BACKUP_CONFIG_REQUIRED')
        try:
            report = create_backup(options['directory'], options['recipient'], options['destination'], options['retention_days'])
        except BackupError as error:
            raise CommandError(str(error)) from None
        except OSError:
            raise CommandError('BACKUP_IO_FAILED') from None
        self.stdout.write(json.dumps(report))
