"""Aggregate diagnostics only: no row contents, SQL text, hosts or credentials."""
import json
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction


class Command(BaseCommand):
    help = 'Read-only database size, estimated row counts, connections and memory settings.'

    def handle(self, **options):
        tables=sorted({model._meta.db_table for model in apps.get_models()})
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute('SELECT pg_database_size(current_database())')
                report={'read_only':True,'database_bytes':cursor.fetchone()[0],'row_counts_are_estimates':True}
                cursor.execute('''SELECT relname, pg_total_relation_size(relid), pg_relation_size(relid),
                    pg_indexes_size(relid), n_live_tup, n_dead_tup, last_autovacuum, last_autoanalyze
                    FROM pg_stat_user_tables WHERE relname = ANY(%s)
                    AND schemaname = ANY(current_schemas(false))
                    ORDER BY pg_total_relation_size(relid) DESC LIMIT 20''',[tables])
                columns=['table','total_bytes','table_bytes','index_bytes','estimated_live_rows','estimated_dead_rows','last_autovacuum','last_autoanalyze']
                report['largest_tables']=[dict(zip(columns,row)) for row in cursor.fetchall()]
                cursor.execute('''SELECT COALESCE(state,'unknown'), count(*) FROM pg_stat_activity
                    WHERE datname=current_database() GROUP BY state''')
                report['connections_by_state']=dict(cursor.fetchall())
                cursor.execute('''SELECT name, setting, unit FROM pg_settings WHERE name = ANY(%s)''',[
                    ['shared_buffers','work_mem','maintenance_work_mem','max_connections','autovacuum']])
                report['settings']={name:{'value':value,'unit':unit} for name,value,unit in cursor.fetchall()}
        except DatabaseError:
            raise CommandError('DB 사용량을 조회하지 못했습니다. DB 접속·조회 권한을 확인해 주세요.') from None
        self.stdout.write(json.dumps(report,ensure_ascii=False,indent=2,default=str))
