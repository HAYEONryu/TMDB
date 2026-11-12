from django.db.models import Func, JSONField


class JSONSubset(Func):
    """Project object keys in PostgreSQL, before large JSON reaches Python.

    Both object and key expressions are compiled by Django; no request text is
    interpolated into SQL. Empty key lists can retain legacy baseline snapshots.
    """
    output_field = JSONField()
    arity = 2

    def __init__(self, document, keys, *, empty_means_all=False):
        self.empty_means_all = empty_means_all
        super().__init__(document, keys)

    def as_postgresql(self, compiler, connection, **extra_context):
        document, document_params = compiler.compile(self.source_expressions[0])
        keys, keys_params = compiler.compile(self.source_expressions[1])
        condition = f'{keys} ? entry.key'
        params = [*document_params, *keys_params]
        if self.empty_means_all:
            condition = f"{keys} = '[]'::jsonb OR {condition}"
            params = [*document_params, *keys_params, *keys_params]
        return (
            "(SELECT COALESCE(jsonb_object_agg(entry.key, entry.value), '{}'::jsonb) "
            f"FROM jsonb_each({document}) AS entry WHERE {condition})", params,
        )
