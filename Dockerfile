# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so the layer is cached while only source changes.
COPY requirements.txt .
RUN pip install --no-cache-dir pip==26.2.1 \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# WhiteNoise collects into STATIC_ROOT at container start; the app user must own it.
RUN useradd --system --create-home appuser \
    && mkdir -p /app/staticfiles \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "python manage.py check --deploy --fail-level WARNING && python manage.py collectstatic --noinput && exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 3 --timeout 60 --access-logfile - --error-logfile -"]
