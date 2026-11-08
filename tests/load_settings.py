"""Opt-in disposable-load diagnosis; never used by a normal app process."""
from scripts.verification_evidence import artifact_path

from config.test_settings import *  # noqa: F403
MIDDLEWARE = [*MIDDLEWARE, 'tests.load_settings.QueryProfileMiddleware']


class QueryProfileMiddleware:
    def __init__(self, get_response): self.get_response=get_response

    def __call__(self, request):
        import json,time
        from django.db import connection
        if not connection.settings_dict['NAME'].startswith('test_tm_'):
            raise RuntimeError('Load diagnosis requires disposable database')
        slow=[]
        def measure(execute,sql,params,many,context):
            start=time.perf_counter()
            try:return execute(sql,params,many,context)
            finally:
                duration=time.perf_counter()-start
                if duration>.2 and sql.startswith('SELECT') and 'FROM "customers_customer"' in sql and 'FOR UPDATE' not in sql:
                    slow.append((sql,params,duration))
        with connection.execute_wrapper(measure):response=self.get_response(request)
        for sql,params,duration in slow[:1]:
            with connection.cursor() as cursor:
                cursor.execute('EXPLAIN (ANALYZE,FORMAT JSON) '+sql,params)
                plan=cursor.fetchone()[0][0]
            def shape(node):
                keys=['Node Type','Relation Name','Actual Rows','Actual Loops','Actual Total Time','Plan Rows']
                return {**{key:node[key] for key in keys if key in node},'Plans':[shape(child) for child in node.get('Plans',[])]}
            row={'request_method':request.method,'duration_seconds':duration,'planning_ms':plan.get('Planning Time'),
                 'execution_ms':plan.get('Execution Time'),'jit':plan.get('JIT'),'total_cost':plan['Plan']['Total Cost'],'plan':shape(plan['Plan'])}
            with (artifact_path('p13-query-profile.jsonl')).open('a') as handle:handle.write(json.dumps(row)+'\n')
        return response
