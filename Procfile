release: python manage.py migrate
web: python manage.py collectstatic --noinput && gunicorn config.wsgi
worker: python manage.py process_optimizations --loop --interval 5
