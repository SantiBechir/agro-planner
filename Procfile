release: python manage.py migrate && python manage.py collectstatic --noinput && python manage.py cargar_input docs/Input.xlsx
web: gunicorn config.wsgi
