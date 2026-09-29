release: python manage.py deploy_release
web: python manage.py check --deploy --fail-level WARNING --settings=config.settings.production && python manage.py collectstatic --noinput --settings=config.settings.production && gunicorn config.wsgi --env DJANGO_SETTINGS_MODULE=config.settings.production
worker: python manage.py process_optimizations --loop --interval 5
