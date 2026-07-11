release: python manage.py migrate && python manage.py cargar_input docs/Input.xlsx
web: python manage.py collectstatic --noinput && gunicorn config.wsgi
worker: python manage.py process_optimizations --loop --interval 5
