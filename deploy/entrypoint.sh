#!/bin/sh
set -eu

# Migrations are applied explicitly before starting web. Never flush or migrate
# an existing database here. Only an entirely empty account table is seeded.
if [ "${1:-}" = "gunicorn" ]; then
    python manage.py ensure_initial_admin
fi
exec "$@"
