release: python manage.py deploy_release
web: python manage.py collectstatic --noinput && gunicorn config.wsgi
worker: python manage.py process_optimizations --loop --interval 5
