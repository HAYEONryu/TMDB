import json
import os
from django.core.management.base import BaseCommand, CommandError
from apps.operations.backups import BackupError, restore_backup


class Command(BaseCommand):
    help = 'Authenticate/decrypt a backup and restore into a NEW tm_restore_* database only.'

    def add_arguments(self, parser):
        parser.add_argument('--archive', required=True)
        parser.add_argument('--identity', default=os.environ.get('BACKUP_IDENTITY_FILE'))
        parser.add_argument('--target', required=True)

    def handle(self, *args, **options):
        if not options['identity']:
            raise CommandError('RESTORE_IDENTITY_REQUIRED')
        try:
            report = restore_backup(options['archive'], options['identity'], options['target'])
        except BackupError as error:
            raise CommandError(str(error)) from None
        except Exception:
            raise CommandError('RESTORE_DATABASE_FAILED') from None
        self.stdout.write(json.dumps(report))
