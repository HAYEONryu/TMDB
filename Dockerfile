FROM python:3.13.18-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY . /app
RUN DJANGO_SECRET_KEY=build-only-fake-key DATABASE_URL=postgresql://tm:fake@postgres/tm_dev python manage.py collectstatic --noinput \
    && useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--worker-class", "gthread", "--threads", "4", "--access-logfile", "/dev/null"]
